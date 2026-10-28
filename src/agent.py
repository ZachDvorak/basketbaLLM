import os
from dataclasses import dataclass, field
from pathlib import Path

from charts import KINDS, MAX_CHARTS_PER_QUESTION, ChartSpec
from db import NBADatabase, format_rows
from llm import make_backend

DEFAULT_PROVIDER = os.environ.get("NBA_PROVIDER", "openai")
DICTIONARY = Path(__file__).resolve().parent.parent / "docs" / "data_dictionary.md"

SYSTEM_PROMPT = """You are a basketball historian and analyst. You answer questions using ONLY the NBA/ABA/BAA season-level database you can query with your tools.

How to work:
1. If you are unsure of table or column names, call get_schema first; it also explains the conventions.
2. Write DuckDB SQL and run it with run_sql. Use the views: player_season (one row per player per season), team_season, league_season, awards, all_star, all_league_teams, draft, players. player_season_team is only for "with team X" splits.
3. Seasons: the `season` column is the year the season ENDS. The 2023-24 season is season = 2024. Always show users the `season_label` form (2023-24), never the raw number.
4. Filter lg = 'NBA' unless the user asks about the ABA or BAA, and say when you did. For careers, aggregate over player_season and group by player_id.
5. Leaderboards need a minimum-games filter (g >= 50 for per-game stats) or minutes filter (total_min >= 1000 for advanced stats). State the filter you used. Do not round before sorting.
6. Player names carry accents: match with the exact spelling or strip_accents(player) ILIKE '%jokic%'.
7. NULL means a stat was not recorded in that era (for example blocks before 1973-74); do not treat it as zero, and mention it when it matters.
8. If a query errors or returns 0 rows, fix it and retry rather than guessing.
9. Never state a statistic that did not come from a query result. This data has NO individual games, playoff player stats, salaries, injuries, tracking data, or predictions. If the question needs those, say so plainly and offer the closest thing the data can answer.
10. Give a short plain-English answer with the key numbers, then one line naming the filters or assumptions used. Do not paste raw SQL unless asked.
11. When the user asks for a chart, graph, plot or graphic (or the request says to include one), first run a query that returns exactly the columns to plot (a text label such as season_label for x, a numeric column for y, and a column like player to split series if comparing), then call make_chart. Order rows in the order they should appear (seasons oldest first). Never say you drew a chart unless make_chart reported success.
"""


@dataclass
class AgentResult:
    answer: str
    queries: list = field(default_factory=list)   # every SQL string the agent ran, in order
    errors: int = 0                               # how many of those failed
    charts: list = field(default_factory=list)    # ChartSpec objects the agent drew; see charts.render_chart


class NBAAgent:
    def __init__(self, db=None, provider=DEFAULT_PROVIDER, model=None, backend=None):
        self.db = db or NBADatabase()
        self.backend = backend or make_backend(provider, model)
        self.provider, self.model = self.backend.name, getattr(self.backend, "model", model)
        self.system = f"{SYSTEM_PROMPT}\nData coverage: {self.db.coverage()}"
        self._queries, self._errors, self._charts, self._last = [], 0, [], None
        self.tools = {"get_schema": self._get_schema, "run_sql": self._run_sql, "make_chart": self._make_chart}

    def _get_schema(self):
        text = DICTIONARY.read_text() if DICTIONARY.exists() else ""
        return f"{text}\n\n## Live schema\n{self.db.live_schema()}"

    def _run_sql(self, sql):
        self._queries.append(sql)
        try:
            columns, rows, truncated = self.db.run_sql(sql)
        except ValueError as exc:
            self._errors += 1
            return f"SQL error: {exc}"
        self._last = (columns, rows)
        return format_rows(columns, rows, truncated)

    def _make_chart(self, kind, title, x, y, series=""):
        """Tool: record a chart drawn from the most recent successful query result."""
        if len(self._charts) >= MAX_CHARTS_PER_QUESTION:
            return f"Chart limit reached ({MAX_CHARTS_PER_QUESTION} per question)."
        if self._last is None:
            return "No data to chart yet. Run a query with run_sql first."
        if kind not in KINDS:
            return f"Unknown chart kind '{kind}'. Use one of {list(KINDS)}."
        columns, rows = self._last
        series = series or ""
        for name in (x, y) + ((series,) if series else ()):
            if name not in columns:
                return f"Column '{name}' is not in the last query result. Its columns are {columns}."
        spec = ChartSpec(kind=kind, title=title, x=x, y=y, series=series, columns=list(columns),
                         rows=[tuple(r) for r in rows])
        try:  # draw it once now so a bad chart is reported to the model while it can still fix it
            from charts import render_chart
            render_chart(spec)
        except ValueError as exc:
            return f"Could not draw that chart: {exc}"
        self._charts.append(spec)
        return f"Chart created: {kind} of {y} by {x}{' split by ' + series if series else ''}. It is shown to the user."

    def ask(self, question, want_chart=False):
        """Answer one question (stateless: each call starts a fresh conversation).

        want_chart=True tells the agent to include a chart (the interface's 'include a chart' option)."""
        self._queries, self._errors, self._charts, self._last = [], 0, [], None
        if want_chart:
            question = f"{question}\n\n(Please also include a chart of the result using make_chart.)"
        answer = self.backend.run(self.system, question, self.tools)
        return AgentResult(answer=answer, queries=list(self._queries), errors=self._errors,
                           charts=list(self._charts))


if __name__ == "__main__":
    import sys

    result = NBAAgent().ask(" ".join(sys.argv[1:]) or "Who led the league in scoring last season?")
    print(result.answer)
    print(f"\n[{len(result.queries)} queries, {result.errors} errors]")
