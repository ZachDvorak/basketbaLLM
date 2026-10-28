"""Ask an OpenAI or Gemini model to write the chat interface (the model does the design and the coding).

    python src/build_app.py --provider gemini                    # first draft -> src/app_generated.py
    python src/build_app.py --provider openai --model <name>     # try another model, then compare the two
    python src/build_app.py --provider gemini --feedback "the answer card is too small; make the header bolder"
    python src/build_app.py --provider gemini --feedback "<paste the error you got when launching>"

With --feedback the model is shown its previous file (--out, or --from) and your note, and revises it.
The model's reply is checked for valid Python and for risky calls, then saved. READ the file before running it:
it will run with your API keys in the environment.
"""
import argparse
import ast
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from llm import make_backend

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
    parser.add_argument("--model", help="a stronger model usually writes better code (see src/list_models.py)")
    parser.add_argument("--out", default=str(ROOT / "src" / "app_generated.py"))
    parser.add_argument("--from", dest="source", help="file to revise (default: --out if it exists)")
    parser.add_argument("--feedback", help="what to change, or paste the error from launching")
    args = parser.parse_args()

    out = Path(args.out)
    if out.resolve() == BASELINE.resolve():
        sys.exit("Refusing to overwrite src/app.py (the plain working version). Use a different --out.")
    previous_path = Path(args.source) if args.source else out
    previous = previous_path.read_text() if args.feedback and previous_path.exists() else None
    if args.feedback and previous is None:
        sys.exit(f"--feedback needs an earlier version to revise, but {previous_path} does not exist yet. "
                 "Run once without --feedback first.")

    backend = make_backend(args.provider, args.model)
    print(f"Asking {backend.name}/{backend.model} to {'revise' if previous else 'write'} the interface...")
    prompt = build_prompt(BRIEF.read_text(), BASELINE.read_text(), previous, args.feedback)
    code, problem, raw = generate(backend, prompt)
    if code is None:
        raw_path = out.with_suffix(".raw.txt")
        raw_path.write_text(raw)
        sys.exit(f"The model's reply was not usable: {problem}. Raw reply saved to {raw_path}. Run it again.")

    out.write_text(code)
    print(f"Saved {out} ({len(code.splitlines())} lines).")
    flagged = risky_lines(code)
    if flagged:
        print("\nReview these lines before running (the brief told the model not to use them):")
        for number, line in flagged:
            print(f"  line {number}: {line}")
    shown = out.resolve().relative_to(ROOT) if out.resolve().is_relative_to(ROOT) else out
    print(f"\nNext: read the file, then run  python {shown}"
          "\nNot happy with it, or it errors? Run this again with --feedback \"...\".")


if __name__ == "__main__":
    main()
