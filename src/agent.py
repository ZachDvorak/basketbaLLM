"""The basketball analytics agent: an LLM (OpenAI or Gemini) + two tools (schema lookup, read-only SQL)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from db import NBADatabase, format_rows
from llm import make_backend

DEFAULT_PROVIDER = os.environ.get("NBA_PROVIDER", "openai")
DICTIONARY = Path(__file__).resolve().parent.parent / "docs" / "data_dictionary.md"

SYSTEM_PROMPT = """You are a basketball analyst. You answer questions using ONLY the NBA database you can query with your tools.

How to work:
1. If you are unsure of table or column names, call get_schema first.
2. Write DuckDB SQL and run it with run_sql. Prefer the player_season and team_season views for season-level questions; use player_games / team_games for single games, streaks, and splits.
3. Always filter season_type (use 'Regular Season' unless the user asks about playoffs). Apply a sensible minimum-games filter on leaderboards (e.g. games >= 40) and say which filter you used.
4. Player names may contain accents (Jokić, Dončić): match with ILIKE and a partial name, e.g. player_name ILIKE '%Joki%'.
5. If a query errors or returns 0 rows, fix it and retry rather than guessing.
6. Never state a statistic that did not come from a query result. If the data cannot answer the question (outside the seasons covered, or a stat we do not store such as salaries, injuries, tracking data, or defensive ratings), say so plainly and offer the closest thing the data can answer.
7. Give a short plain-English answer with the key numbers, then one line naming the filters or assumptions used (season, season type, minimum games). Do not paste raw SQL unless asked.
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
