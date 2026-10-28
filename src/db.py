"""DuckDB layer: loads the CSVs, defines analytics views, and runs guarded read-only SQL."""
import threading
from pathlib import Path

import duckdb

from schema import STAT_COLS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_ROWS = 50          # rows returned to the model per query
QUERY_TIMEOUT_S = 20   # kill runaway queries

REQUIRED_TABLES = {"team_games": "team_games.csv", "player_games": "player_games.csv"}
OPTIONAL_TABLES = {"teams": "teams.csv", "players": "players.csv"}

# Pre-aggregated views so the model does not have to re-derive per-game averages and shooting
# percentages (the most common source of wrong answers) on every question.
VIEWS = """
CREATE VIEW player_season AS
SELECT
    player_id,
    any_value(player_name)                         AS player_name,
    season,
    season_type,
    string_agg(DISTINCT team_abbreviation, '/')    AS teams,
    count(*)                                       AS games,
    round(avg(min), 1)                             AS mpg,
    sum(pts)                                       AS total_pts,
    round(avg(pts), 1)                             AS ppg,
    sum(reb)                                       AS total_reb,
    round(avg(reb), 1)                             AS rpg,
    sum(ast)                                       AS total_ast,
    round(avg(ast), 1)                             AS apg,
    round(avg(stl), 1)                             AS spg,
    round(avg(blk), 1)                             AS bpg,
    round(avg(tov), 1)                             AS tpg,
    sum(fgm) AS fgm, sum(fga) AS fga,
    round(sum(fgm) / nullif(sum(fga), 0), 3)       AS fg_pct,
    sum(fg3m) AS fg3m, sum(fg3a) AS fg3a,
    round(sum(fg3m) / nullif(sum(fg3a), 0), 3)     AS fg3_pct,
    sum(ftm) AS ftm, sum(fta) AS fta,
    round(sum(ftm) / nullif(sum(fta), 0), 3)       AS ft_pct,
    round(sum(pts) / nullif(2 * (sum(fga) + 0.44 * sum(fta)), 0), 3) AS ts_pct,
    round(avg(plus_minus), 1)                      AS avg_plus_minus
FROM player_games
GROUP BY player_id, season, season_type;

CREATE VIEW team_season AS
SELECT
    t.team_id,
    any_value(t.team_name)                         AS team_name,
    any_value(t.team_abbreviation)                 AS team_abbreviation,
    t.season,
    t.season_type,
    count(*)                                       AS games,
    sum((t.wl = 'W')::INT)                         AS wins,
    sum((t.wl = 'L')::INT)                         AS losses,
    round(avg((t.wl = 'W')::INT), 3)               AS win_pct,
    round(avg(t.pts), 1)                           AS ppg,
    round(avg(o.pts), 1)                           AS opp_ppg,
    round(avg(t.pts - o.pts), 1)                   AS avg_margin,
    round(avg(t.fg3m), 1)                          AS fg3m_pg,
    round(sum(t.fg3m) / nullif(sum(t.fg3a), 0), 3) AS fg3_pct,
    round(avg(t.reb), 1)                           AS rpg,
    round(avg(t.ast), 1)                           AS apg,
    round(avg(t.tov), 1)                           AS tpg
FROM team_games t
JOIN team_games o ON t.game_id = o.game_id AND t.team_id <> o.team_id
GROUP BY t.team_id, t.season, t.season_type;
"""


class NBADatabase:
    def __init__(self, data_dir=DATA_DIR):
        self.con = duckdb.connect(":memory:")
        self.tables = []
        for table, filename in {**REQUIRED_TABLES, **OPTIONAL_TABLES}.items():
            path = Path(data_dir) / filename
            if not path.exists():
                if table in REQUIRED_TABLES:
                    raise FileNotFoundError(
                        f"{path} not found. Run `python src/pull_data.py` first (see README)."
                    )
                continue
            self.con.execute(
                f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto(?, header = true)", [str(path)]
            )
            self.tables.append(table)
        self._coerce_stat_columns()
        self.con.execute(VIEWS)
        # Lock down AFTER loading: the model's SQL cannot read files or change settings.
        self.con.execute("SET enable_external_access = false")
        self.con.execute("SET lock_configuration = true")

    def _coerce_stat_columns(self):
        """A stray text value (e.g. 'DNP') makes DuckDB read a whole stat column as VARCHAR, which breaks avg()/sum().
        Convert such columns to numbers; values that are not numeric become NULL."""
        for table in ("player_games", "team_games"):
            types = dict(self.con.execute(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ?", [table]
            ).fetchall())
            for column in STAT_COLS:
                if types.get(column) == "VARCHAR":
                    self.con.execute(
                        f"ALTER TABLE {table} ALTER COLUMN {column} SET DATA TYPE DOUBLE USING TRY_CAST({column} AS DOUBLE)")

    def run_sql(self, sql):
        """Run one SELECT/WITH statement. Returns (columns, rows, truncated). Raises ValueError on misuse."""
        try:
            statements = duckdb.extract_statements(sql)
        except duckdb.Error as exc:
            raise ValueError(f"SQL could not be parsed: {exc}") from exc
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("Only a single read-only SELECT statement is allowed.")

        timer = threading.Timer(QUERY_TIMEOUT_S, self.con.interrupt)
        timer.start()
        try:
            cursor = self.con.execute(sql)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchmany(MAX_ROWS + 1)
        except duckdb.Error as exc:
            raise ValueError(str(exc)) from exc
        finally:
            timer.cancel()
        truncated = len(rows) > MAX_ROWS
        return columns, rows[:MAX_ROWS], truncated

    def coverage(self):
        """A one-line description of what the data covers, shown to the model and the user."""
        seasons, start, end, players, teams = self.con.execute(
            "SELECT string_agg(DISTINCT season, ', ' ORDER BY season), min(game_date), max(game_date), "
            "count(DISTINCT player_id), count(DISTINCT team_id) FROM player_games"
        ).fetchone()
        types = [r[0] for r in self.con.execute("SELECT DISTINCT season_type FROM team_games").fetchall()]
        return (f"Seasons: {seasons}. Season types: {', '.join(types)}. "
                f"Game dates {start} to {end}. {players} players, {teams} teams.")

    def live_schema(self):
        """Table/view names with column names and types, straight from DuckDB."""
        lines = []
        for name, kind in self.con.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_type, table_name"
        ).fetchall():
            cols = self.con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position", [name]
            ).fetchall()
            lines.append(f"{name} ({kind.lower()}): " + ", ".join(f"{c} {t}" for c, t in cols))
        return "\n".join(lines)


def format_rows(columns, rows, truncated):
    lines = [",".join(columns)]
    lines += [",".join("" if v is None else str(v) for v in row) for row in rows]
    if truncated:
        lines.append(f"... truncated to the first {MAX_ROWS} rows; add LIMIT/filters to narrow the query")
    if not rows:
        lines.append("(0 rows)")
    return "\n".join(lines)
