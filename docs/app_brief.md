# Brief: build the chat interface for the NBA History Analyst

You are writing the user interface for a basketball question-answering agent. The agent already works. Your job is
the interface only. Make it polished, distinctive and pleasant to use. The visual design is entirely your call:
layout, theme, colors, typography, header, icons, spacing, and any small touches that make it feel finished.
A basketball-inspired look is welcome, but readability comes first.

## What the agent gives you (do not change it)

```python
from agent import NBAAgent            # the file is run as `python src/<yourfile>.py`, so this import works

agent = NBAAgent(provider="openai", model=None)   # provider is "openai" or "gemini"; model=None uses the default
result = agent.ask("Who led the NBA in scoring in 2023-24?")

result.answer    # str: the plain-English answer (may contain markdown)
result.queries   # list[str]: every SQL query the agent ran, in order
result.errors    # int: how many of those queries failed (the agent retries, so this is informational)

agent.db.coverage()   # str: one or two sentences describing the data's seasons and limits
```

- `ask()` takes roughly 5 to 60 seconds and is stateless (each question is independent, so there is no chat memory).
- `ask()` can raise exceptions (bad API key, rate limit, network). Catch them and show a short, friendly message.
- The data is season-level (one row per player per season), regular season only. There are no game logs, playoff
  player stats, salaries or injuries. The agent will say so when asked about those.
- API keys are already in the environment (`OPENAI_API_KEY`, `GEMINI_API_KEY`). Never ask for, display or log a key.

## Must have

1. A question box and a button (Enter should also submit).
2. A provider choice (OpenAI or Gemini). Create each `NBAAgent` once and reuse it; do not rebuild it per question.
3. A clear loading state while the agent works, and a friendly error state if it fails.
4. The answer shown prominently and readably.
5. A collapsible "How I got this" section that shows the SQL queries, formatted as code. Hide it when there are none.
6. Clickable example questions, using these:
   - Who led the NBA in points per game in 2023-24 (minimum 50 games)?
   - Compare Michael Jordan and LeBron James by career points, rebounds and assists per game.
   - Which team had the best record in 2015-16?
   - Who has the most career three-pointers made in the NBA?
   - Who won Rookie of the Year in 2023-24?
   - How many points did Michael Jordan score in the 1993 NBA Finals?
7. A short note showing `agent.db.coverage()` so users know what the data covers.
8. A history of the questions asked in this session, so users can scroll back (the agent itself has no memory).
9. It must work on a phone-sized screen too.

## Technical constraints

- One Python file, using Gradio (already installed; code for the installed version is below). Use only APIs that
  exist in that version.
- Launch with `share=True` so it works in Google Colab, and put the launch call under `if __name__ == "__main__":`.
- No other third-party packages. No `eval`, `exec`, `subprocess`, `os.system`, file writes, or network calls of
  your own. Everything goes through `NBAAgent`.
- Add a short comment at the top saying what the file is. Keep the code readable: someone new to Gradio should be
  able to follow it.

## Output format

Reply with exactly one fenced ```python code block containing the complete file, and nothing else.
