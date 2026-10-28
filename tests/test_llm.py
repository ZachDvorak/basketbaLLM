"""Offline tests for the provider layer using fake clients (no API keys, no network)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from agent import NBAAgent  # noqa: E402
from db import NBADatabase  # noqa: E402
from llm import OpenAIBackend, TOOL_SPECS, gemini_functions, pick_best_model, with_retry  # noqa: E402
from make_fixture import make  # noqa: E402


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return NBADatabase(make(tmp_path_factory.mktemp("fake_nba")))


class FakeResponses:
    """Scripted stand-in for client.responses: first asks for run_sql, then answers."""

    def __init__(self, sql):
        self.sql, self.calls = sql, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            call = NS(type="function_call", name="run_sql", call_id="c1", arguments=json.dumps({"sql": self.sql}))
            return NS(id="r1", output=[call], output_text="")
        return NS(id="r2", output=[NS(type="message")], output_text="  There are 3 teams.  ")


def fake_openai(sql):
    backend = OpenAIBackend.__new__(OpenAIBackend)
    backend.model, backend.client = "fake", NS(responses=FakeResponses(sql))
    return backend


def test_openai_loop_runs_tool_and_returns_text(db):
    backend = fake_openai("SELECT count(*) FROM team_season")
    agent = NBAAgent(db, backend=backend)
    result = agent.ask("How many teams?")
    assert result.answer == "There are 3 teams."
    assert result.queries == ["SELECT count(*) FROM team_season"] and result.errors == 0
    first, second = backend.client.responses.calls
    assert first["instructions"] == agent.system and second["instructions"] == agent.system
    assert second["previous_response_id"] == "r1"
    output = second["input"][0]
    assert output["type"] == "function_call_output" and output["call_id"] == "c1" and "3" in output["output"]


def test_bad_sql_is_reported_to_model_not_raised(db):
    backend = fake_openai("DROP VIEW team_season")
    result = NBAAgent(db, backend=backend).ask("x")
    assert result.errors == 1
    assert "SQL error" in backend.client.responses.calls[1]["input"][0]["output"]


def test_unknown_tool_does_not_crash(db):
    backend = fake_openai("SELECT 1")
    bad = NS(type="function_call", name="nope", call_id="c9", arguments="{}")
    backend.client.responses.create = lambda **kw: NS(id="r", output=[bad], output_text="")
    assert "limit" in backend.run("s", "q", {"run_sql": lambda sql: "x"})


def test_gemini_schema_is_generated_from_functions():
    from google import genai
    from google.genai import types

    client = genai.Client(api_key="fake")._api_client
    decls = [types.FunctionDeclaration.from_callable(client=client, callable=f)
             for f in gemini_functions({"get_schema": lambda: "", "run_sql": lambda sql: ""})]
    names = {d.name: d for d in decls}
    assert set(names) == {"get_schema", "run_sql", "make_chart"}
    assert "sql" in names["run_sql"].parameters.properties
    assert names["run_sql"].parameters.required == ["sql"]
    assert names["make_chart"].parameters.required == ["kind", "title", "x", "y"]  # series is optional


def test_gemini_functions_call_through():
    fns = {f.__name__: f for f in gemini_functions({"get_schema": lambda: "S", "run_sql": lambda sql: f"ran {sql}",
                                                    "make_chart": lambda **kw: f"chart {kw['kind']} {kw['series']!r}"})}
    assert fns["get_schema"]() == "S" and fns["run_sql"]("SELECT 1") == "ran SELECT 1"
    assert fns["make_chart"]("bar", "t", "x", "y") == "chart bar ''"


def test_retry_retries_rate_limits_then_gives_up(monkeypatch):
    monkeypatch.setattr("llm.time.sleep", lambda s: None)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise type("E", (Exception,), {"code": 429})()
        return "ok"

    assert with_retry(flaky) == "ok" and len(attempts) == 3

    def fatal():
        raise type("E", (Exception,), {"code": 400})()

    with pytest.raises(Exception):
        with_retry(fatal)


def test_openai_strict_tool_specs_are_valid():
    """OpenAI strict mode needs every property listed as required and additionalProperties false."""
    for spec in TOOL_SPECS:
        params = spec["parameters"]
        assert params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"]), spec["name"]


def test_pick_best_openai_model_takes_newest_full_size_text_model():
    ids = ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-5", "gpt-5-2025-08-07", "gpt-5-chat-latest", "gpt-5-codex",
           "gpt-5-mini", "gpt-5-nano", "gpt-5-pro", "gpt-5.1", "gpt-5.1-codex", "gpt-image-1", "gpt-realtime",
           "o3", "text-embedding-3-large", "tts-1", "whisper-1"]
    assert pick_best_model("openai", ids) == "gpt-5.1"
    assert pick_best_model("openai", [i for i in ids if i != "gpt-5.1"]) == "gpt-5"
    assert pick_best_model("openai", ["gpt-5-mini", "o3", "whisper-1"]) is None


def test_pick_best_gemini_model_takes_newest_stable_flash():
    ids = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash-image",
           "gemini-2.5-pro", "gemini-3-pro-preview", "gemini-flash-latest", "gemini-embedding-001"]
    assert pick_best_model("gemini", ids) == "gemini-2.5-flash"
    assert pick_best_model("gemini", ["gemini-2.5-pro"]) is None
