# NBA Analyst Agent

A natural-language analytics agent over NBA box-score data. A user asks a basketball question in plain
English; the agent looks up the schema, writes SQL against CSV-backed tables, checks the result, and answers
in plain English with the numbers and the filters it used.

**Why this project:** it is a small, fully measurable version of the "ask questions of our business data"
problem. Swap the NBA CSVs for corporate extracts and the same architecture, evaluation method, and failure
modes apply.

---

## 1. Goals and non-goals

**Goals**
1. Answer factual and analytical basketball questions correctly from data, with no invented statistics.
2. Say "the data can't answer that" when it can't (salaries, injuries, seasons outside the data).
3. Measure accuracy with a fixed test set, then improve it and show the before/after.
4. Document what transfers to a business setting.

**Non-goals**: training an LLM from scratch, live scores, predictions, play-by-play or tracking analysis.

**Design principle:** the model never *remembers* statistics. It *finds* them. Numbers come only from query
results, which is what makes the answers checkable.

## 2. Architecture

```
 user question
      |
      v
 +-----------+   get_schema()    +--------------------------+
 |  Claude   | ----------------> | data dictionary + live   |
 |  (agent   |   run_sql(sql)    | schema                   |
 |   loop)   | ----------------> +--------------------------+
 |           | <---------------- DuckDB (in-memory, read-only)
 +-----------+   rows as CSV      tables loaded from data/*.csv
      |                           views: player_season, team_season
      v
 plain-English answer + filters used
```

| Piece | File | Job |
|---|---|---|
| Data pull | `src/pull_data.py` | Downloads box scores via `nba_api`, validates, writes CSVs |
| Database | `src/db.py` | Loads CSVs into DuckDB, defines season views, guards SQL |
| Agent | `src/agent.py` | System prompt, two tools, tool-use loop (Anthropic SDK tool runner) |
| Eval | `src/evaluate.py`, `eval/questions.csv` | 32 questions with gold SQL; automatic + LLM-judge grading |
| UI | `src/app.py` | Optional Gradio chat |
| Docs | `docs/data_dictionary.md` | Column meanings and query gotchas; the agent reads this |
| Tests | `tests/` | Offline tests on fake data (pipeline, SQL guard, gold SQL, grader) |

**Why DuckDB and not SQLite:** DuckDB reads CSVs directly, needs no database server or file, and runs in
Colab with one `pip install`. The data stays CSV; SQL is just the query language.

**Why views:** `player_season` and `team_season` pre-compute per-game averages, shooting percentages, true
shooting, wins, and opponent points. Without them the model re-derives these every time, and that is where
most wrong answers come from. It is the same reason business teams build a semantic layer.

**Safety guards (`db.py`):** one statement only, `SELECT` only, external file access disabled after load,
configuration locked, 20 second timeout, 50-row result cap.

## 3. Data

Source: [`nba_api`](https://github.com/swar/nba_api), which wraps the public `stats.nba.com` endpoints.
Check the NBA's terms of use before using the data beyond this class project.

Default scope: seasons 2021-22 through 2025-26, regular season and playoffs.

| File | Grain | Approx rows (5 seasons) |
|---|---|---|
| `player_games.csv` | player x game | 130k–150k |
| `team_games.csv` | team x game | 13k |
| `teams.csv` | team | 30 |
| `players.csv` | player directory | ~5k |

Full column list: [`docs/data_dictionary.md`](docs/data_dictionary.md).

### Known risk: stats.nba.com blocks cloud IPs
`stats.nba.com` frequently times out or refuses requests from cloud providers, and Colab is one. If
`pull_data.py` fails in Colab, in order of preference:
1. Run `python src/pull_data.py` **on your laptop**, then upload the `data/` folder to Colab (or Drive).
2. Re-run it; downloads are cached in `data/raw/` and resume where they stopped.
3. Use `--proxy` with a proxy you are permitted to use.
4. Build the same CSVs from another source (for example a Kaggle NBA box-score dataset) by renaming columns to
   match the data dictionary. `player_games` and `team_games` are the only required tables.

## 4. Setup (Colab)

1. Zip this folder as `nba-agent.zip` and open `notebooks/colab_runner.ipynb` in Colab (or `git clone`).
2. Add `ANTHROPIC_API_KEY` under Colab **Secrets** and enable notebook access.
3. Run the notebook top to bottom: install, pull data, run tests, ask a question, evaluate.

Locally:

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python src/pull_data.py
python -m pytest tests -q
python src/agent.py "Who led the league in assists per game in 2024-25?"
python src/evaluate.py --judge
```

## 5. Evaluation

`eval/questions.csv` has 32 questions in 8 categories: lookup, leaderboard, team, comparison, trend,
game-level, playoffs, derived, and **unanswerable** (the agent must decline, not invent).
Each answerable question has a gold SQL query. The harness runs the gold SQL against your real data, so the
expected answers stay correct whichever seasons you pull.

Two graders:
- **auto**: every value in the gold result must appear in the answer (numbers within rounding).
- **judge** (`--judge`): a small model compares the answer with the gold result. More forgiving of phrasing.

Both have blind spots, so read a sample of failures by hand. Failures are recorded in `results/eval_*.csv`
with the queries the agent ran, so you can tag each as: wrong column, bad join, missing filter, misread
question, hallucinated number, or grader error.

**Experiments that make a good write-up** (change one thing at a time, rerun the full set):
1. Baseline: no `get_schema` description, no views (query raw tables only).
2. Add the data dictionary and views (the current design).
3. Add 5–10 worked question-to-SQL examples to the system prompt.
4. Model comparison: `--model claude-haiku-5-5` vs `claude-sonnet-5-5` vs `claude-opus-5-5`; plot accuracy vs cost.
5. Expand the question set with your own questions, especially the ones you tried that failed.

Report accuracy overall and per category, and the failure-type breakdown. A statement like "view and
dictionary changes moved accuracy from X% to Y% and removed most wrong-column errors" is the result worth presenting.

> The gold SQL for each question was checked for validity against the schema on synthetic data. It has **not**
> yet been checked against real NBA data. After your pull, run `python src/evaluate.py --check-gold` and
> sanity check a few results against Basketball-Reference before trusting any score.

## 6. Build plan

| Phase | Work | Done when |
|---|---|---|
| 1. Data | Pull CSVs, run tests, skim `team_games`/`player_games` for oddities (missing seasons, duplicate rows) | `--check-gold` returns sensible numbers |
| 2. Agent v1 | Run `agent.py` on 10 questions by hand | End-to-end answers with queries shown |
| 3. Measure | Full eval, categorize failures | Baseline accuracy recorded |
| 4. Improve | Experiments in section 5, one change at a time | Before/after table |
| 5. Present | UI demo plus results and lessons | Short deck or notebook walkthrough |

## 7. Mapping to your business work

| Here | At work |
|---|---|
| `player_games` / `team_games` CSVs | Fact tables or exports |
| `player_season` / `team_season` views | Governed metric definitions (a semantic layer) |
| `data_dictionary.md` | Metric glossary, the single most valuable artifact |
| Min-games filter, `season_type` filter | Business rules the agent must apply every time |
| Eval set with gold SQL | Regression tests you rerun on every prompt or model change |
| "Data can't answer that" cases | Trust: an agent that refuses beats one that guesses |
| SQL guard | Read-only access, row limits, timeouts for any real data source |

## 8. Risks and limitations

- **Wrong-but-plausible answers** are the main risk. Mitigation: views, dictionary, eval, showing the queries.
- **Ambiguity** ("best player", "last season") needs a stated assumption. The prompt requires the agent to name its filters.
- **Cost**: the full eval makes a few hundred API calls. Run `--limit 5` first and check usage in the Anthropic console before scaling up.
- **Stateless**: each question starts fresh, so follow-ups like "what about Embiid?" don't work yet.
- **Data freshness**: the CSVs are a snapshot. Re-run `pull_data.py` (delete `data/raw/` for the current season) to refresh.

## 9. Stretch ideas

- Multi-turn memory for follow-up questions.
- A chart tool (matplotlib) so the agent can answer "show me ..." questions.
- A "scouting report" tool that combines several queries.
- Retrieval over articles or notes for qualitative context.
- Fine-tune a small open model (e.g. 1B–3B, LoRA) on synthetic question-to-SQL pairs for this schema and compare it with the API model on your eval. This is the "build a model" angle if your cohort needs one.
