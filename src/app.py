"""Tiny chat UI:  python src/app.py   (in Colab, share=True gives a public link)."""
import gradio as gr

from agent import NBAAgent

agent = NBAAgent()


def respond(message, history):
    result = agent.ask(message)
    sql = "\n\n".join(f"```sql\n{q}\n```" for q in result.queries)
    return result.answer + (f"\n\n<details><summary>Queries used</summary>\n\n{sql}\n\n</details>" if sql else "")


gr.ChatInterface(
    respond,
    title="NBA Analyst Agent",
    description=agent.db.coverage(),
    examples=["Who led the league in assists per game in 2024-25?",
              "Compare Jokić and Embiid in 2023-24.",
              "How many 40-point games did Devin Booker have in 2023-24?"],
).launch(share=True)
