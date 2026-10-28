"""Print the models your API keys can use, so you can pick --model values that exist today.

    python src/list_models.py
"""
import os


def main():
    if os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI

        print("OpenAI models:")
        for name in sorted(m.id for m in OpenAI().models.list()):
            print("  ", name)
    else:
        print("OPENAI_API_KEY not set; skipping OpenAI")

    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        from google import genai

        print("Gemini models that support generateContent:")
        for m in genai.Client().models.list():
            if "generateContent" in (m.supported_actions or []):
                print("  ", m.name.removeprefix("models/"))
    else:
        print("GEMINI_API_KEY / GOOGLE_API_KEY not set; skipping Gemini")


if __name__ == "__main__":
    main()
