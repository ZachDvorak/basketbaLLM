"""DuckDB layer: loads the Kaggle CSVs, defines clean analytics views, and runs guarded read-only SQL.

The raw CSVs are loaded into the `raw` schema (never shown to the model). Everything the agent sees is a view
in the main schema with friendly column names, 'NA' turned into NULL, and traded players de-duplicated.
"""
import os
import threading
from pathlib import Path

import duckdb

from schema import FILES

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_ROWS = 50          # rows returned to the model per query
QUERY_TIMEOUT_S = 20   # kill runaway queries

VIEWS = r"""
-- Kaggle/Basketball-Reference label a season by the year it ENDS (2024 = the 2023-24 season).
CREATE MACRO season_label(s) AS (s - 1)::VARCHAR || '-' || lpad((s % 100)::VARCHAR, 2, '0');

-- One row per player per season per team. Traded players have a combined row (team like '2TM') PLUS one row per team.
CREATE VIEW player_season_team AS
SELECT
    pg.season, season_label(pg.season) AS season_label, pg.lg, pg.player_id, pg.player, pg.age, pg.team, pg.pos,
    pg.g, pg.gs,
    pg.mp_per_game AS mpg, pg.pts_per_game AS ppg, pg.trb_per_game AS rpg, pg.orb_per_game AS orpg,
    pg.drb_per_game AS drpg, pg.ast_per_game AS apg, pg.stl_per_game AS spg, pg.blk_per_game AS bpg,
    pg.tov_per_game AS tpg, pg.pf_per_game AS pfpg,
    pg.fg_per_game AS fgm_pg, pg.fga_per_game AS fga_pg, pg.x3p_per_game AS fg3m_pg, pg.x3pa_per_game AS fg3a_pg,
    pg.ft_per_game AS ftm_pg, pg.fta_per_game AS fta_pg,
    pg.fg_percent AS fg_pct, pg.x3p_percent AS fg3_pct, pg.ft_percent AS ft_pct, pg.e_fg_percent AS efg_pct,
    t.mp AS total_min, t.pts AS total_pts, t.trb AS total_reb, t.ast AS total_ast, t.stl AS total_stl,
    t.blk AS total_blk, t.tov AS total_tov, t.fg AS fgm, t.fga, t.x3p AS fg3m, t.x3pa AS fg3a, t.ft AS ftm, t.fta,
    t.trp_dbl AS triple_doubles,
    a.per, a.ts_percent AS ts_pct, a.usg_percent AS usg_pct, a.ast_percent AS ast_pct, a.trb_percent AS reb_pct,
    a.stl_percent AS stl_pct, a.blk_percent AS blk_pct, a.tov_percent AS tov_pct, a.ows, a.dws, a.ws, a.ws_48,
    a.obpm, a.dbpm, a.bpm, a.vorp
FROM raw.player_per_game pg
LEFT JOIN raw.player_totals t
       ON t.season = pg.season AND t.lg = pg.lg AND t.player_id = pg.player_id AND t.team = pg.team
LEFT JOIN raw.advanced a
       ON a.season = pg.season AND a.lg = pg.lg AND a.player_id = pg.player_id AND a.team = pg.team;

-- One row per player per season: the combined row for traded players, otherwise their only row. Use this by default.
CREATE VIEW player_season AS
SELECT * FROM player_season_team
QUALIFY row_number() OVER (
    PARTITION BY season, lg, player_id
    ORDER BY regexp_matches(team, '^[0-9]+TM$') DESC, g DESC) = 1;

-- One row per team per season (league-average rows removed).
CREATE VIEW team_season AS
SELECT
    s.season, season_label(s.season) AS season_label, s.lg, s.team AS team_name, s.abbreviation AS team_abbrev,
    s.playoffs AS made_playoffs, tg.g AS games, s.w AS wins, s.l AS losses,
    round(s.w * 1.0 / nullif(s.w + s.l, 0), 3) AS win_pct, s.pw AS pythag_wins, s.pl AS pythag_losses,
    tg.pts_per_game AS ppg, og.opp_pts_per_game AS opp_ppg, s.mov AS margin, s.sos, s.srs,
    s.o_rtg, s.d_rtg, s.n_rtg, s.pace, s.ts_percent AS ts_pct, s.e_fg_percent AS efg_pct,
    s.tov_percent AS tov_pct, s.orb_percent AS orb_pct, s.drb_percent AS drb_pct,
    s.x3p_ar AS fg3a_rate, s.f_tr AS ft_rate, s.age AS avg_age,
    tg.fg_percent AS fg_pct, tg.x3p_per_game AS fg3m_pg, tg.x3p_percent AS fg3_pct, tg.trb_per_game AS rpg,
    tg.ast_per_game AS apg, tg.stl_per_game AS spg, tg.blk_per_game AS bpg, tg.tov_per_game AS tpg,
    s.arena, s.attend AS attendance, s.attend_g AS attendance_per_game
FROM raw.team_summaries s
LEFT JOIN raw.team_stats_per_game tg ON tg.season = s.season AND tg.lg = s.lg AND tg.team = s.team
LEFT JOIN raw.opponent_stats_per_game og ON og.season = s.season AND og.lg = s.lg AND og.team = s.team
WHERE s.team <> 'League Average';

-- One row per league per season: league-wide averages (for comparing eras).
CREATE VIEW league_season AS
SELECT
    s.season, season_label(s.season) AS season_label, s.lg, tg.pts_per_game AS ppg_per_team, s.pace,
    s.o_rtg AS off_rating, s.ts_percent AS ts_pct, s.e_fg_percent AS efg_pct, s.x3p_ar AS fg3a_rate,
    s.f_tr AS ft_rate, tg.x3p_per_game AS fg3m_pg_per_team, tg.fg_percent AS fg_pct, s.age AS avg_age
FROM raw.team_summaries s
LEFT JOIN raw.team_stats_per_game tg ON tg.season = s.season AND tg.lg = s.lg AND tg.team = s.team
WHERE s.team = 'League Average';

-- Award voting results (MVP, ROY, DPOY, ...). winner = TRUE for the award winner.
CREATE VIEW awards AS
SELECT season, season_label(season) AS season_label, award, player, player_id, age, "first" AS first_place_votes,
       pts_won, pts_max, share, winner
FROM raw.awards;

CREATE VIEW all_star AS
SELECT season, season_label(season) AS season_label, lg, player, player_id, team AS all_star_team, replaced
FROM raw.all_star;

-- All-NBA / All-Defense / All-Rookie / All-ABA / All-BAA selections.
CREATE VIEW all_league_teams AS
SELECT season, season_label(season) AS season_label, lg, type AS team_type, number_tm AS team_number,
       player, player_id, position
FROM raw.all_league;

-- draft_year is the calendar year of the draft (NOT the end-year convention used by `season`).
CREATE VIEW draft AS
SELECT season AS draft_year, lg, overall_pick, round, tm AS team, player, player_id, college
FROM raw.draft;

CREATE VIEW players AS
SELECT player_id, player, pos, ht_in_in AS height_in, wt AS weight_lb, birth_date, colleges,
       "from" AS first_season, "to" AS last_season, debut, hof AS hall_of_famer
FROM raw.players;

-- Maps team abbreviations (Basketball-Reference style: BRK, CHO, PHO ...) to names, by season.
CREATE VIEW team_abbrev AS
SELECT season, lg, team AS team_name, abbreviation, playoffs AS made_playoffs
FROM raw.team_abbrev;
"""


def find_csv(data_dir, filename):
    """Find a CSV by name anywhere under data_dir (case-insensitive), so Kaggle's folder layout does not matter."""
    wanted = filename.lower()
    for path in Path(data_dir).rglob("*.csv"):
        if path.name.lower() == wanted:
            return path
    return None


class NBADatabase:
    def __init__(self, data_dir=None):
        data_dir = Path(data_dir or os.environ.get("NBA_DATA_DIR") or DATA_DIR)
        self.data_dir = data_dir
        self.con = duckdb.connect(":memory:")
        self.con.execute("CREATE SCHEMA raw")
        self._load_raw(data_dir)
        self.con.execute(VIEWS)
        # Lock down AFTER loading: the model's SQL cannot read files or change settings.
        self.con.execute("SET enable_external_access = false")
        self.con.execute("SET lock_configuration = true")

    def _load_raw(self, data_dir):
        missing_files, missing_cols = [], {}
        for table, (filename, columns) in FILES.items():
            path = find_csv(data_dir, filename) if Path(data_dir).exists() else None
            if path is None:
                missing_files.append(filename)
                continue
            # 'NA' is Basketball-Reference's missing-value marker; reading it as NULL makes columns numeric.
            self.con.execute(
                f"CREATE TABLE raw.{table} AS "
                "SELECT * FROM read_csv_auto(?, header = true, nullstr = 'NA', sample_size = -1)", [str(path)])
            have = {r[0].lower() for r in self.con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'raw' AND table_name = ?",
                [table]).fetchall()}
            gone = [c for c in columns if c not in have]
            if gone:
                missing_cols[filename] = gone
        if missing_files or missing_cols:
            lines = [f"The data in {data_dir} does not match what the agent expects."]
            if missing_files:
                found = sorted(p.name for p in Path(data_dir).rglob("*.csv")) if Path(data_dir).exists() else []
                lines.append(f"Missing files: {missing_files}")
                lines.append(f"CSV files found: {found or 'none (is the folder path right?)'}")
            for filename, cols in missing_cols.items():
                lines.append(f"{filename} is missing columns: {cols}")
            lines.append("Run `python src/inspect_csvs.py <folder>` to see what your files contain.")
            raise FileNotFoundError("\n".join(lines))

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
        """A short description of what the data covers, shown to the model and the user."""
        first, last, leagues, players = self.con.execute(
            "SELECT min(season), max(season), string_agg(DISTINCT lg, ', ' ORDER BY lg), count(DISTINCT player_id) "
            "FROM player_season").fetchone()
        return (f"Seasons {first - 1}-{first % 100:02d} through {last - 1}-{last % 100:02d} "
                f"(season values {first} to {last}). Leagues: {leagues}. {players:,} players. "
                "Player statistics are regular season only; there are no individual game logs.")

    def live_schema(self):
        """View/table names with column names and types, straight from DuckDB (main schema only)."""
        lines = []
        for name, kind in self.con.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_type, table_name"
        ).fetchall():
            cols = self.con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position", [name]
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
