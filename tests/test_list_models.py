"""list_models.py with fake provider clients (no keys, no network)."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import list_models  # noqa: E402


def run(monkeypatch, capsys, models=None, error=None, env=None):
    from google import genai

    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {"GEMINI_API_KEY": "gem-key"}).items():
        monkeypatch.setenv(key, value)
    seen = {}

    class FakeClient:
        def __init__(self, api_key=None):
            seen["api_key"] = api_key
            self.models = NS(list=self._list)

        def _list(self):
            if error:
                raise error
            return iter(models)

    monkeypatch.setattr(genai, "Client", FakeClient)
    with pytest.raises(SystemExit) as exc:
        list_models.main()
    return capsys.readouterr().out, exc.value.code, seen


def test_lists_models_that_support_generate_content(monkeypatch, capsys):
    models = [NS(name="models/gemini-a", supported_actions=["generateContent"]),
              NS(name="models/embed-b", supported_actions=["embedContent"])]
    out, code, _ = run(monkeypatch, capsys, models)
    assert "gemini-a" in out and "embed-b" not in out and code == 0


def test_falls_back_to_all_models_when_sdk_reports_no_actions(monkeypatch, capsys):
    models = [NS(name="models/gemini-a", supported_actions=None), NS(name="models/gemini-b")]
    out, code, _ = run(monkeypatch, capsys, models)
    assert "gemini-a" in out and "gemini-b" in out and "did not say" in out and code == 0


def test_explicit_key_prefers_gemini_key_over_google_key(monkeypatch, capsys):
    _, _, seen = run(monkeypatch, capsys, [NS(name="models/g", supported_actions=["generateContent"])],
                     env={"GEMINI_API_KEY": "gem-key", "GOOGLE_API_KEY": "other-key"})
    assert seen["api_key"] == "gem-key"


def test_both_keys_set_and_different_prints_a_note(monkeypatch, capsys):
    out, _, _ = run(monkeypatch, capsys, [], env={"GEMINI_API_KEY": "a", "GOOGLE_API_KEY": "b"})
    assert "both set" in out


def test_rejected_key_is_explained_without_printing_the_key(monkeypatch, capsys):
    err = type("ClientError", (Exception,), {"code": 400})("API key not valid. Please pass a valid API key.")
    out, code, _ = run(monkeypatch, capsys, error=err, env={"GEMINI_API_KEY": "SECRET-KEY-123"})
    assert "Hint" in out and "AI Studio" in out and "SECRET-KEY-123" not in out and code == 1


def test_one_provider_failing_does_not_hide_the_other(monkeypatch, capsys):
    from types import SimpleNamespace
    import openai

    monkeypatch.setattr(openai, "OpenAI", lambda: SimpleNamespace(models=SimpleNamespace(
        list=lambda: [SimpleNamespace(id="gpt-x")])))
    err = type("ServerError", (Exception,), {"code": 429})("quota")
    out, code, _ = run(monkeypatch, capsys, error=err, env={"OPENAI_API_KEY": "o", "GEMINI_API_KEY": "g"})
    assert "gpt-x" in out and "Rate limited" in out and code == 1


def test_missing_keys_are_skipped_cleanly(monkeypatch, capsys):
    out, code, _ = run(monkeypatch, capsys, [], env={})
    assert "no API key set" in out and code == 0
