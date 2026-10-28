"""Print the models your API keys can use, so you can pick --model values that exist today.

    python src/list_models.py

If a provider fails, this prints what went wrong in plain words (and the raw error message, never the key).
"""
import os
import sys

from llm import gemini_api_key, pick_best_model


def explain(exc, provider):
    """Turn an SDK exception into advice."""
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    text = f"{type(exc).__name__}: {exc}"
    hint = ""
    if status in (400, 401, 403) or "API key" in str(exc) or "API_KEY" in str(exc):
        hint = ("The key was rejected. Check that the Colab secret holds the key itself (no quotes or spaces), "
                "that 'Notebook access' is switched on for it, and that it is a "
                + ("Google AI Studio key (aistudio.google.com/apikey)." if provider == "gemini"
                   else "valid OpenAI key with billing set up."))
    elif status == 404:
        hint = "The service did not recognise the request. Upgrade the SDK: pip install -U " + (
            "google-genai" if provider == "gemini" else "openai")
    elif status == 429:
        hint = "Rate limited or out of quota. Wait a minute and try again, or check the plan and billing."
    elif isinstance(exc, (ConnectionError, TimeoutError)) or "Connect" in type(exc).__name__:
        hint = "Network problem reaching the provider. Check the Colab connection and try again."
    return f"{provider} failed.\n  {text}" + (f"\n  Hint: {hint}" if hint else "")


def suggest(provider, ids):
    best = pick_best_model(provider, ids)
    if best:
        print(f"Suggested for building the app (build_app.py picks this automatically): {best}")
    else:
        print("No suggestion: pass --model to build_app.py with a model from the list above.")


def list_openai():
    from openai import OpenAI

    ids = sorted(m.id for m in OpenAI().models.list())
    print("OpenAI models:")
    for name in ids:
        print("  ", name)
    suggest("openai", ids)


def list_gemini():
    from google import genai

    if os.environ.get("GEMINI_API_KEY") and os.environ.get("GOOGLE_API_KEY") \
            and os.environ["GEMINI_API_KEY"] != os.environ["GOOGLE_API_KEY"]:
        print("Note: GEMINI_API_KEY and GOOGLE_API_KEY are both set and differ. Using GEMINI_API_KEY.")
    models = list(genai.Client(api_key=gemini_api_key()).models.list())
    names = lambda items: sorted((getattr(m, "name", None) or "").removeprefix("models/") for m in items)
    usable = [m for m in models if "generateContent" in (getattr(m, "supported_actions", None) or [])]
    if usable:
        print(f"Gemini models that support generateContent ({len(usable)} of {len(models)}):")
        shown = usable
    else:  # some SDK versions do not report supported actions; show everything rather than nothing
        print(f"Gemini models ({len(models)}; this SDK version did not say which support generateContent, "
              "so pick one named gemini-*):")
        shown = models
    listed = [name for name in names(shown) if name]
    for name in listed:
        print("  ", name)
    suggest("gemini", listed)


def main():
    failed = False
    for provider, present, run in (
        ("openai", bool(os.environ.get("OPENAI_API_KEY")), list_openai),
        ("gemini", bool(gemini_api_key()), list_gemini),
    ):
        if not present:
            print(f"{provider}: no API key set ({'OPENAI_API_KEY' if provider == 'openai' else 'GEMINI_API_KEY or GOOGLE_API_KEY'}); skipping")
            continue
        try:
            run()
        except Exception as exc:  # report and keep going so one provider does not hide the other
            failed = True
            print(explain(exc, provider))
        print()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
