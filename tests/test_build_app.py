"""Offline tests for build_app.py using a fake model (no API keys)."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import build_app  # noqa: E402

GOOD = "Here you go:\n```python\nfrom agent import NBAAgent\nprint('hi')\n```\nEnjoy!"


@pytest.fixture(autouse=True)
def no_network_model_lookup(monkeypatch):
    monkeypatch.setattr(build_app, "best_model", lambda provider: "picked-model")


class FakeBackend:
    name, model = "fake", "fake-1"

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return self.reply


def test_extract_code_handles_fences_and_chatter():
    assert build_app.extract_code(GOOD) == "from agent import NBAAgent\nprint('hi')\n"
    assert build_app.extract_code("```\nx = 1\n```") == "x = 1\n"
    assert build_app.extract_code("no code here") is None


def test_generate_accepts_good_code():
    code, problem, _ = build_app.generate(FakeBackend(GOOD), "prompt")
    assert problem is None and "NBAAgent" in code


@pytest.mark.parametrize("reply, fragment", [
    ("just words", "no ```python"),
    ("```python\ndef broken(:\n```", "syntax error"),
    ("```python\nprint('not connected')\n```", "NBAAgent"),
])
def test_generate_rejects_unusable_replies(reply, fragment):
    code, problem, _ = build_app.generate(FakeBackend(reply), "prompt")
    assert code is None and fragment in problem


def test_risky_lines_are_flagged_but_comments_are_not():
    code = "import subprocess\n# eval( in a comment\nx = open('f', 'w')\nsafe = 1\n"
    assert [n for n, _ in build_app.risky_lines(code)] == [1, 3]


def test_prompt_contains_contract_baseline_and_feedback():
    prompt = build_app.build_prompt("BRIEF", "BASELINE", previous="PREV", feedback="bigger header", gradio="5.0")
    for piece in ("BRIEF", "BASELINE", "PREV", "bigger header", "5.0"):
        assert piece in prompt
    assert "PREV" not in build_app.build_prompt("BRIEF", "BASELINE", gradio="5.0")


def test_real_brief_defines_the_agent_contract():
    brief = build_app.BRIEF.read_text()
    for piece in ("NBAAgent", "result.queries", "coverage()", "share=True", "exactly one fenced"):
        assert piece in brief


def test_cli_refuses_to_overwrite_plain_app(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "openai", "--out", str(build_app.BASELINE)])
    with pytest.raises(SystemExit) as exc:
        build_app.main()
    assert "Refusing" in str(exc.value)


def test_cli_end_to_end_with_fake_model(monkeypatch, tmp_path):
    out = tmp_path / "gen.py"
    backend = FakeBackend(GOOD)
    monkeypatch.setattr(build_app, "make_backend", lambda provider, model: backend)
    monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "gemini", "--out", str(out), "--no-verify"])
    build_app.main()
    assert out.read_text().startswith("from agent import NBAAgent")

    # revision: the model is shown its previous file plus the feedback
    monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "gemini", "--out", str(out), "--feedback", "darker",
                                      "--no-verify"])
    build_app.main()
    assert "from agent import NBAAgent" in backend.prompts[1] and "darker" in backend.prompts[1]


def test_cli_feedback_without_previous_file_explains(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "gemini", "--out", str(tmp_path / "none.py"),
                                      "--feedback", "x"])
    with pytest.raises(SystemExit) as exc:
        build_app.main()
    assert "without --feedback" in str(exc.value)


# ---- the test launch and the automatic fix loop (needs gradio; skipped if it is not installed) ----
GOOD_APP = """
from agent import NBAAgent
import gradio as gr

agent = NBAAgent()

def respond(question):
    return agent.ask(question).answer

with gr.Blocks() as demo:
    box, out = gr.Textbox(), gr.Markdown()
    gr.Button("Ask").click(respond, box, out)

if __name__ == "__main__":
    demo.launch(share=True)
"""
# the exact bug seen in Colab: `_js` was renamed `js` in newer Gradio
BAD_APP = GOOD_APP.replace(".click(respond, box, out)", ".click(respond, box, out, _js='() => 1')")


def fenced(code):
    return f"```python\n{code}\n```"


@pytest.fixture
def gradio_installed():
    pytest.importorskip("gradio")


def test_smoke_test_passes_a_valid_app(gradio_installed, tmp_path):
    path = tmp_path / "ok.py"
    path.write_text(GOOD_APP)
    assert build_app.smoke_test(path) == (True, "")


def test_smoke_test_reports_the_colab_error(gradio_installed, tmp_path):
    path = tmp_path / "bad.py"
    path.write_text(BAD_APP)
    ok, message = build_app.smoke_test(path)
    assert not ok and "_js" in message and "TypeError" in message


def test_smoke_test_catches_an_app_that_never_launches(gradio_installed, tmp_path):
    path = tmp_path / "nolaunch.py"
    path.write_text(GOOD_APP.replace("demo.launch(share=True)", "pass"))
    ok, message = build_app.smoke_test(path)
    assert not ok and "never called launch" in message


def test_model_is_sent_the_launch_error_and_fixes_its_own_code(gradio_installed, monkeypatch, tmp_path):
    out = tmp_path / "gen.py"
    replies = iter([fenced(BAD_APP), fenced(GOOD_APP)])

    class Sequence(FakeBackend):
        def complete(self, prompt):
            self.prompts.append(prompt)
            return next(replies)

    backend = Sequence("")
    monkeypatch.setattr(build_app, "make_backend", lambda provider, model: backend)
    monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "openai", "--out", str(out)])
    build_app.main()
    assert len(backend.prompts) == 2
    assert "_js" in backend.prompts[1] and "Launching the app failed" in backend.prompts[1]
    assert "_js" not in out.read_text()  # the saved file is the model's fixed version


def test_gives_up_after_max_fixes_and_says_so(gradio_installed, monkeypatch, tmp_path):
    out = tmp_path / "gen.py"
    backend = FakeBackend(fenced(BAD_APP))
    monkeypatch.setattr(build_app, "make_backend", lambda provider, model: backend)
    monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "openai", "--out", str(out), "--max-fixes", "1"])
    with pytest.raises(SystemExit) as exc:
        build_app.main()
    assert "still fails to launch" in str(exc.value) and "--feedback" in str(exc.value)
    assert len(backend.prompts) == 2 and out.exists()


# ---- unusable replies (syntax errors, no code block) are sent back to the model too ----
SYNTAX_BROKEN = "```python\nfrom agent import NBAAgent\nx = f'unterminated\n```"


class Sequence(FakeBackend):
    def __init__(self, replies):
        super().__init__("")
        self.replies = iter(replies)

    def complete(self, prompt):
        self.prompts.append(prompt)
        return next(self.replies)


def test_syntax_error_reply_is_sent_back_and_fixed(monkeypatch, tmp_path):
    out = tmp_path / "gen.py"
    backend = Sequence([SYNTAX_BROKEN, GOOD])
    monkeypatch.setattr(build_app, "make_backend", lambda provider, model: backend)
    monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "openai", "--out", str(out), "--no-verify"])
    build_app.main()
    assert len(backend.prompts) == 2
    assert "syntax error" in backend.prompts[1] and "unterminated" in backend.prompts[1]  # it sees its own code
    assert out.read_text().startswith("from agent import NBAAgent\nprint")


def test_unrecoverable_replies_leave_the_existing_file_untouched(monkeypatch, tmp_path):
    out = tmp_path / "gen.py"
    out.write_text("# my previous version\n")
    backend = FakeBackend(SYNTAX_BROKEN)
    monkeypatch.setattr(build_app, "make_backend", lambda provider, model: backend)
    monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "openai", "--out", str(out), "--max-fixes", "1",
                                      "--no-verify"])
    with pytest.raises(SystemExit) as exc:
        build_app.main()
    assert "not changed" in str(exc.value) and "stronger model" in str(exc.value)
    assert out.read_text() == "# my previous version\n" and len(backend.prompts) == 2
    assert out.with_suffix(".raw.txt").exists()


def test_syntax_error_then_launch_error_then_success(gradio_installed, monkeypatch, tmp_path):
    out = tmp_path / "gen.py"
    backend = Sequence([SYNTAX_BROKEN, fenced(BAD_APP), fenced(GOOD_APP)])
    monkeypatch.setattr(build_app, "make_backend", lambda provider, model: backend)
    monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "openai", "--out", str(out), "--max-fixes", "2"])
    build_app.main()
    assert len(backend.prompts) == 3 and "_js" not in out.read_text()


def test_best_model_is_chosen_automatically_but_never_over_an_explicit_model(monkeypatch, tmp_path):
    chosen = []
    monkeypatch.setattr(build_app, "make_backend", lambda provider, model: chosen.append(model) or FakeBackend(GOOD))
    for extra in ([], ["--model", "my-model"]):
        monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "openai", "--out", str(tmp_path / "a.py"),
                                          "--no-verify", *extra])
        build_app.main()
    assert chosen == ["picked-model", "my-model"]


def test_model_listing_failure_falls_back_to_the_default(monkeypatch, tmp_path, capsys):
    def boom(provider):
        raise RuntimeError("no key")

    chosen = []
    monkeypatch.setattr(build_app, "best_model", boom)
    monkeypatch.setattr(build_app, "make_backend", lambda provider, model: chosen.append(model) or FakeBackend(GOOD))
    monkeypatch.setattr(sys, "argv", ["build_app", "--provider", "openai", "--out", str(tmp_path / "a.py"), "--no-verify"])
    build_app.main()
    assert chosen == [None] and "Could not list models" in capsys.readouterr().out


def test_brief_describes_charts():
    brief = build_app.BRIEF.read_text()
    for piece in ("result.charts", "want_chart=True", "render_chart", "to_png", "Include a chart"):
        assert piece in brief


def test_smoke_stub_exercises_charts(gradio_installed, tmp_path):
    path = tmp_path / "chartapp.py"
    path.write_text(GOOD_APP.replace("return agent.ask(question).answer",
                                     "r = agent.ask(question, want_chart=True)\n    from charts import render_chart\n"
                                     "    render_chart(r.charts[0])\n    return r.answer"))
    assert build_app.smoke_test(path) == (True, "")
