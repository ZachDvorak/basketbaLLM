"""Ask an OpenAI or Gemini model to write the chat interface (the model does the design and the coding).

    python src/build_app.py --provider gemini                    # first draft -> src/app_generated.py
    python src/build_app.py --provider openai --model <name>     # try another model, then compare the two
    python src/build_app.py --provider gemini --feedback "the answer card is too small; make the header bolder"
    python src/build_app.py --provider gemini --feedback "<paste the error you got when launching>"

With --feedback the model is shown its previous file (--out, or --from) and your note, and revises it.
The model's reply is checked for valid Python and for risky calls, then saved. Then the app is test-launched
with a stand-in agent (no API calls). If launching fails, the error goes back to the model to fix, up to --max-fixes
times, so version mismatches like Gradio's renamed arguments are repaired by the model, not by you.
READ the final file before running it: it will run with your API keys in the environment.
"""
import argparse
import ast
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from llm import best_model, make_backend

ROOT = Path(__file__).resolve().parent.parent
BRIEF = ROOT / "docs" / "app_brief.md"
BASELINE = ROOT / "src" / "app.py"
RISKY = ("os.system", "subprocess", "eval(", "exec(", "__import__", "requests.", "urllib", "socket",
         "shutil", "os.remove", "os.environ", "open(", "pickle")


def installed_gradio():
    try:
        return version("gradio")
    except PackageNotFoundError:
        return "unknown (not installed here)"


def build_prompt(brief, baseline, previous=None, feedback=None, gradio=None):
    parts = [brief, f"\n## Environment\nInstalled Gradio version: {gradio or installed_gradio()}\n",
             "\n## Current plain version, for reference (it works but looks basic)\n```python\n"
             f"{baseline}\n```\n"]
    if previous:
        parts.append(f"\n## Your previous version\n```python\n{previous}\n```\n")
    if feedback:
        parts.append(f"\n## Revision request from the person using it\n{feedback}\n\n"
                     "Apply this to your previous version and return the complete updated file.\n")
    return "".join(parts)


def extract_code(text):
    match = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() + "\n" if match else None


def risky_lines(code):
    return [(n, line.strip()) for n, line in enumerate(code.splitlines(), 1)
            if any(token in line for token in RISKY) and not line.strip().startswith("#")]


# Runs the generated file with a stand-in `agent` module and a launch() that starts the server without blocking,
# so construction errors (wrong Gradio arguments) show up without API keys or model calls.
SMOKE = r"""
import runpy, sys, types
stub = types.ModuleType("agent")
from charts import ChartSpec
class _Result:
    answer, queries, errors = "A test answer.", ["SELECT 1"], 0
    charts = [ChartSpec("bar", "Test chart", "season_label", "ppg", columns=["season_label", "ppg"],
                        rows=[("2022-23", 25.0), ("2023-24", 27.5)])]
class _Db:
    def coverage(self):
        return "Seasons 1946-47 through 2025-26."
class NBAAgent:
    def __init__(self, *args, **kwargs):
        self.db = _Db()
    def ask(self, question, want_chart=False):
        return _Result()
stub.NBAAgent, stub.AgentResult = NBAAgent, _Result
sys.modules["agent"] = stub
import gradio as gr
launched = []
_launch = gr.Blocks.launch
def launch(self, *args, **kwargs):
    kwargs.update(prevent_thread_lock=True, share=False, quiet=True)
    _launch(self, *args, **kwargs)
    launched.append(1)
    self.close()
gr.Blocks.launch = launch
runpy.run_path(sys.argv[1], run_name="__main__")
if not launched:
    sys.exit("The file ran but never called launch(). Put demo.launch(share=True) under "
             "if __name__ == '__main__':")
print("SMOKE_OK")
"""


def smoke_test(path, timeout=90):
    """Returns (ok, message). message is the tail of the error output when not ok."""
    try:
        run = subprocess.run([sys.executable, "-c", SMOKE, str(path)], capture_output=True, text=True,
                             timeout=timeout, cwd=ROOT / "src")
    except subprocess.TimeoutExpired:
        return False, f"The app did not finish starting within {timeout} seconds."
    if run.returncode == 0 and "SMOKE_OK" in run.stdout:
        return True, ""
    tail = "\n".join((run.stderr or run.stdout).strip().splitlines()[-25:])
    return False, tail or "The app exited without an error message."


def generate(backend, prompt):
    """Returns (code or None, problem or None, raw model reply)."""
    raw = backend.complete(prompt)
    code = extract_code(raw)
    if code is None:
        return None, "the reply had no ```python code block", raw
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return None, f"the code has a syntax error on line {exc.lineno}: {exc.msg}", raw
    if "NBAAgent" not in code:
        return None, "the code never uses NBAAgent, so it is not connected to the agent", raw
    return code, None, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["openai", "gemini"], required=True)
    parser.add_argument("--model", help="default: the strongest suitable model your key can use (see src/list_models.py)")
    parser.add_argument("--out", default=str(ROOT / "src" / "app_generated.py"))
    parser.add_argument("--from", dest="source", help="file to revise (default: --out if it exists)")
    parser.add_argument("--feedback", help="what to change, or paste the error from launching")
    parser.add_argument("--max-fixes", type=int, default=2,
                        help="how many times to send a launch error back to the model (default 2)")
    parser.add_argument("--no-verify", action="store_true", help="skip the test launch")
    args = parser.parse_args()

    out = Path(args.out)
    if out.resolve() == BASELINE.resolve():
        sys.exit("Refusing to overwrite src/app.py (the plain working version). Use a different --out.")
    previous_path = Path(args.source) if args.source else out
    previous = previous_path.read_text() if args.feedback and previous_path.exists() else None
    if args.feedback and previous is None:
        sys.exit(f"--feedback needs an earlier version to revise, but {previous_path} does not exist yet. "
                 "Run once without --feedback first.")

    model = args.model
    if model is None:  # bigger models write much more reliable code than the -mini default
        try:
            model = best_model(args.provider)
            print(f"Chose {args.provider}/{model} as the strongest suitable model your key can use "
                  "(override with --model).")
        except Exception as exc:
            print(f"Could not list models ({type(exc).__name__}); using the default model.")
    backend = make_backend(args.provider, model)
    print(f"Asking {backend.name}/{backend.model} to {'revise' if previous else 'write'} the interface...")
    brief, baseline = BRIEF.read_text(), BASELINE.read_text()
    prompt = build_prompt(brief, baseline, previous, args.feedback)
    shown = out.resolve().relative_to(ROOT) if out.resolve().is_relative_to(ROOT) else out
    code, verified = None, args.no_verify
    for attempt in range(args.max_fixes + 1):
        last_try = attempt == args.max_fixes
        new_code, problem, raw = generate(backend, prompt)
        if new_code is None:  # unusable reply (no code block, or a syntax error): let the model fix it too
            print(f"\nThe model's reply was not usable: {problem}.")
            if last_try:
                raw_path = out.with_suffix(".raw.txt")
                raw_path.write_text(raw)
                kept = f"{shown} was not changed. " if out.exists() else ""
                sys.exit(f"Still unusable after {args.max_fixes} automatic fixes. {kept}The last raw reply is "
                         f"saved at {raw_path}. Run this again, or try --model with a stronger model "
                         "(see src/list_models.py); small models often struggle with long files.")
            print(f"Sending that back to the model (fix {attempt + 1} of {args.max_fixes})...")
            prompt = build_prompt(brief, baseline, extract_code(raw) or code or previous,
                                  f"Your last reply could not be used: {problem}. Return the complete corrected "
                                  "file in one fenced python code block.")
            continue
        code = new_code
        out.write_text(code)
        print(f"Saved {out} ({len(code.splitlines())} lines).")
        if args.no_verify:
            break
        ok, error = smoke_test(out)
        if ok:
            print("Test launch passed: the app starts without errors.")
            verified = True
            break
        print(f"\nTest launch failed:\n{error}\n")
        if last_try:
            break
        print(f"Sending the error back to the model (fix {attempt + 1} of {args.max_fixes})...")
        prompt = build_prompt(brief, baseline, code,
                              "Launching the app failed with the error below. Fix it, using only calls that "
                              f"exist in the installed Gradio version, and return the complete file.\n\n{error}")

    flagged = risky_lines(code)
    if flagged:
        print("\nReview these lines before running (the brief told the model not to use them):")
        for number, line in flagged:
            print(f"  line {number}: {line}")
    if verified:
        print(f"\nNext: read the file, then run  python {shown}"
              "\nNot happy with how it looks? Run this again with --feedback \"...\".")
    else:
        sys.exit(f"\nThe app still fails to launch after {args.max_fixes} automatic fixes. The file is saved at "
                 f"{shown}. Run this again with --feedback and the error above, or try --model with a stronger "
                 "model (see src/list_models.py).")


if __name__ == "__main__":
    main()
