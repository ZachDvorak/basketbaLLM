"""The basketball analytics agent: Claude + two tools (schema lookup, read-only SQL) over the CSV data."""
import os
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
from anthropic import beta_tool

from db import NBADatabase, format_rows

# Swap for a cheaper model (e.g. "claude-haiku-5-5") once the eval shows quality holds.
MODEL = os.environ.get("NBA_AGENT_MODEL", "claude-opus-5-5")
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
    def __init__(self, db=None, model=MODEL):
        self.db = db or NBADatabase()
        self.model = model
        self.client = anthropic.Anthropic()
        self.system = f"{SYSTEM_PROMPT}\nData coverage: {self.db.coverage()}"
        self._queries, self._errors = [], 0

        agent = self

        @beta_tool
        def get_schema() -> str:
            """Return the data dictionary and the live list of tables, views, and columns."""
            text = DICTIONARY.read_text() if DICTIONARY.exists() else ""
            return f"{text}\n\n## Live schema\n{agent.db.live_schema()}"

        @beta_tool
        def run_sql(sql: str) -> str:
            """Run one read-only DuckDB SELECT query against the NBA data and return up to 50 rows as CSV.

            Args:
                sql: A single SELECT (or WITH ... SELECT) statement.
            """
            agent._queries.append(sql)
            try:
                return format_rows(*agent.db.run_sql(sql))
            except ValueError as exc:
                agent._errors += 1
                return f"SQL error: {exc}"

        self.tools = [get_schema, run_sql]

    def ask(self, question):
        """Answer one question (stateless: each call starts a fresh conversation)."""
        self._queries, self._errors = [], 0
        runner = self.client.beta.messages.tool_runner(
            model=self.model,
            max_tokens=16000,
            system=self.system,
            tools=self.tools,
            messages=[{"role": "user", "content": question}],
        )
        final = runner.until_done()
        answer = "".join(b.text for b in final.content if b.type == "text").strip()
        if final.stop_reason == "refusal":
            answer = answer or "The model declined to answer this request."
        return AgentResult(answer=answer, queries=list(self._queries), errors=self._errors)


if __name__ == "__main__":
    import sys

    result = NBAAgent().ask(" ".join(sys.argv[1:]) or "Who led the league in scoring last season?")
    print(result.answer)
    print(f"\n[{len(result.queries)} queries, {result.errors} errors]")
