"""Score the agent against eval/questions.csv.

    python src/evaluate.py --check-gold            # run only the gold SQL (no API key needed)
    python src/evaluate.py --limit 5               # quick smoke test
    python src/evaluate.py --judge                 # also grade with an LLM judge (more forgiving)
    python src/evaluate.py --model claude-haiku-5-5

Two scores per question:
  auto   - every value in the gold SQL result appears in the answer text (numbers within rounding)
  judge  - a small model compares the answer with the gold result (only with --judge)
Always read a sample of failures by hand: both graders have blind spots.
"""
import argparse
import csv
import re
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from db import NBADatabase

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "eval" / "questions.csv"
RESULTS = ROOT / "results"
JUDGE_MODEL = "claude-haiku-5-5"
REFUSAL_HINTS = ("don't have", "do not have", "not in the", "isn't in", "is not in", "not available",
                 "doesn't", "does not", "cannot", "can't", "unable", "no data", "outside", "not cover")


def load_questions():
    with open(QUESTIONS, newline="") as f:
        return list(csv.DictReader(f))


def numbers_in(text):
    found = []
    for token in re.findall(r"-?\d[\d,]*\.?\d*", text):
        try:
            found.append(float(token.replace(",", "").rstrip(".")))
        except ValueError:
            pass
    return found


def cell_found(cell, answer, answer_numbers):
    if cell is None:
        return True
    if isinstance(cell, bool):
        return True  # booleans are labels (e.g. is_home); the surrounding numbers carry the answer
    if isinstance(cell, (int, float, Decimal)):
        value = float(cell)
        tol = 0.5 if value == int(value) else 0.051
        return any(abs(n - c) <= tol for n in answer_numbers for c in (value, value * 100))
    text = str(cell).lower()
    return text in answer.lower() or text.split()[-1] in answer.lower()


def auto_grade(gold_rows, answer, is_unanswerable):
    if is_unanswerable:
        return any(h in answer.lower() for h in REFUSAL_HINTS)
    if not gold_rows:
        return False
    nums = numbers_in(answer)
    return all(cell_found(c, answer, nums) for row in gold_rows[:5] for c in row)


def judge_grade(client, question, gold_text, answer):
    prompt = (
        f"Question: {question}\n\nGround-truth query result:\n{gold_text}\n\nCandidate answer:\n{answer}\n\n"
        "Does the candidate answer agree with the ground truth? Rounding differences and extra context are fine; "
        "wrong names or materially different numbers are not. If the ground truth says the data cannot answer "
        "the question, the candidate must say so instead of inventing a number. Reply with exactly CORRECT or INCORRECT."
    )
    reply = client.messages.create(
        model=JUDGE_MODEL, max_tokens=2000, output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in reply.content if b.type == "text").strip().upper()
    return text.startswith("CORRECT")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check-gold", action="store_true", help="only run gold SQL and print results")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--model")
    args = parser.parse_args()

    db = NBADatabase()
    questions = load_questions()
    if args.ids:
        questions = [q for q in questions if q["id"] in args.ids]
    if args.limit:
        questions = questions[: args.limit]

    gold = {}
    for q in questions:
        if q["gold_sql"].strip():
            gold[q["id"]] = db.run_sql(q["gold_sql"])[1]

    if args.check_gold:
        for q in questions:
            print(f"[{q['id']}] ({q['category']}) {q['question']}")
            print("    ", gold.get(q["id"], "expected: the agent should say the data cannot answer this"))
        return

    from agent import MODEL, NBAAgent

    agent = NBAAgent(db, model=args.model or MODEL)
    client = agent.client if args.judge else None
    rows = []
    for q in questions:
        started = time.time()
        gold_rows = gold.get(q["id"], [])
        unanswerable = not q["gold_sql"].strip()
        try:
            result = agent.ask(q["question"])
            answer, queries, errors = result.answer, result.queries, result.errors
        except Exception as exc:  # keep the run going; record the failure
            answer, queries, errors = f"ERROR {type(exc).__name__}: {exc}", [], 0
        auto = auto_grade(gold_rows, answer, unanswerable)
        judged = ""
        if args.judge:
            gold_text = "(data cannot answer this)" if unanswerable else "\n".join(map(str, gold_rows[:5]))
            judged = judge_grade(client, q["question"], gold_text, answer)
        rows.append({
            "id": q["id"], "category": q["category"], "question": q["question"], "answer": answer,
            "gold": "" if unanswerable else str(gold_rows[:5]), "auto_pass": auto, "judge_pass": judged,
            "n_queries": len(queries), "n_sql_errors": errors, "seconds": round(time.time() - started, 1),
            "queries": " ||| ".join(queries),
        })
        print(f"[{q['id']:>2}] auto={'PASS' if auto else 'FAIL'}"
              f"{' judge=' + ('PASS' if judged else 'FAIL') if args.judge else ''}  {q['question'][:70]}")

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"eval_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    def rate(subset, key):
        return f"{sum(bool(r[key]) for r in subset)}/{len(subset)}" if subset else "-"

    print(f"\nModel: {agent.model}   Results: {out}")
    print(f"Overall  auto {rate(rows, 'auto_pass')}" + (f"   judge {rate(rows, 'judge_pass')}" if args.judge else ""))
    for category in sorted({r['category'] for r in rows}):
        subset = [r for r in rows if r['category'] == category]
        print(f"  {category:<13} auto {rate(subset, 'auto_pass')}"
              + (f"   judge {rate(subset, 'judge_pass')}" if args.judge else ""))


if __name__ == "__main__":
    main()
