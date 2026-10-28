import os
from dataclasses import dataclass, field
from pathlib import Path

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
"""


@dataclass
class AgentResult:
    answer: str
    queries: list = field(default_factory=list)   # every SQL string the agent ran, in order
    errors: int = 0                               # how many of those failed


class NBAAgent:
    def __init__(self, db=None, provider=DEFAULT_PROVIDER, model=None, backend=None):
        self.db = db or NBADatabase()
        self.backend = backend or make_backend(provider, model)
        self.provider, self.model = self.backend.name, getattr(self.backend, "model", model)
        self.system = f"{SYSTEM_PROMPT}\nData coverage: {self.db.coverage()}"
        self._queries, self._errors = [], 0
        self.tools = {"get_schema": self._get_schema, "run_sql": self._run_sql}

    def _get_schema(self):
        text = DICTIONARY.read_text() if DICTIONARY.exists() else ""
        return f"{text}\n\n## Live schema\n{self.db.live_schema()}"

    def _run_sql(self, sql):
        self._queries.append(sql)
        try:
            return format_rows(*self.db.run_sql(sql))
        except ValueError as exc:
            self._errors += 1
            return f"SQL error: {exc}"

    def ask(self, question):
        """Answer one question (stateless: each call starts a fresh conversation)."""
        self._queries, self._errors = [], 0
        answer = self.backend.run(self.system, question, self.tools)
        return AgentResult(answer=answer, queries=list(self._queries), errors=self._errors)


if __name__ == "__main__":
    import sys

    result = NBAAgent().ask(" ".join(sys.argv[1:]) or "Who led the league in scoring last season?")
    print(result.answer)
    print(f"\n[{len(result.queries)} queries, {result.errors} errors]")
