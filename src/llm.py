"""Provider adapters: one tool-calling loop for OpenAI and one for Google Gemini.

Both backends expose the same method:  run(system, question, tools) -> final answer text
where `tools` maps a tool name to a plain Python function that returns a string.
"""
import json
import os
import re
import time

# Starting points only. Model names change often: run `python src/list_models.py` to see what your key can use,
# then set NBA_OPENAI_MODEL / NBA_GEMINI_MODEL or pass --model.
DEFAULT_MODELS = {
    "openai": os.environ.get("NBA_OPENAI_MODEL", "gpt-5-mini"),
    "gemini": os.environ.get("NBA_GEMINI_MODEL", "gemini-2.5-flash"),
}
MAX_TOOL_STEPS = 10

TOOL_SPECS = [
    {
        "name": "get_schema",
        "description": "Return the data dictionary and the live list of tables, views, and columns.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "run_sql",
        "description": "Run one read-only DuckDB SELECT query against the NBA data and return up to 50 rows as CSV.",
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SELECT (or WITH ... SELECT) statement."}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
    {
        "name": "make_chart",
        "description": ("Draw a chart from the rows of the MOST RECENT successful run_sql result. Run a query that "
                        "returns exactly the columns to plot first (text labels such as season_label for x, a "
                        "numeric column for y). The chart is shown to the user next to your answer."),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["bar", "line", "scatter"],
                         "description": "bar to compare categories, line for change over seasons, scatter for two numbers"},
                "title": {"type": "string", "description": "A short descriptive chart title."},
                "x": {"type": "string", "description": "Column for the horizontal axis."},
                "y": {"type": "string", "description": "Numeric column to plot."},
                "series": {"type": "string",
                           "description": "Column that splits the data into colored series (for example player), or an empty string for one series."},
            },
            "required": ["kind", "title", "x", "y", "series"],
            "additionalProperties": False,
        },
    },
]


def gemini_api_key():
    """GEMINI_API_KEY first (the Colab secret this project sets). google-genai alone prefers GOOGLE_API_KEY when
    both are set, which can silently pick a different key, so we choose explicitly."""
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def with_retry(call, attempts=5):
    """Retry rate limits (429) and transient server errors (5xx) with exponential backoff.
    Free tiers hit 429 often, so this matters most for Gemini."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            if attempt == attempts or status not in (429, 500, 502, 503, 504):
                raise
            time.sleep(min(60, 4 * 2 ** (attempt - 1)))


class OpenAIBackend:
    name = "openai"

    def __init__(self, model=None):
        from openai import OpenAI

        self.model = model or DEFAULT_MODELS["openai"]
        self.client = OpenAI()  # reads OPENAI_API_KEY

    def _create(self, **kwargs):
        return with_retry(lambda: self.client.responses.create(model=self.model, **kwargs))

    def run(self, system, question, tools, max_steps=MAX_TOOL_STEPS):
        specs = [{"type": "function", "strict": True, **s} for s in TOOL_SPECS]
        resp = self._create(instructions=system, input=question, tools=specs)
        for _ in range(max_steps):
            calls = [item for item in resp.output if item.type == "function_call"]
            if not calls:
                return resp.output_text.strip()
            outputs = []
            for call in calls:
                try:
                    result = tools[call.name](**json.loads(call.arguments or "{}"))
                except Exception as exc:  # bad JSON, unknown tool, wrong args: tell the model, don't crash
                    result = f"Tool error: {type(exc).__name__}: {exc}"
                outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": result})
            # `instructions` do not carry over with previous_response_id, so send them every turn.
            resp = self._create(instructions=system, previous_response_id=resp.id, input=outputs, tools=specs)
        return "I could not finish within the tool-call limit. Please try a narrower question."

    def complete(self, prompt):
        return self._create(input=prompt).output_text.strip()


def gemini_functions(tools):
    """Plain functions with type hints + docstrings: the google-genai SDK builds the tool schema from them."""

    def get_schema() -> str:
        """Return the data dictionary and the live list of tables, views, and columns."""
        return tools["get_schema"]()

    def run_sql(sql: str) -> str:
        """Run one read-only DuckDB SELECT query against the NBA data and return up to 50 rows as CSV.

        Args:
            sql: A single SELECT (or WITH ... SELECT) statement.
        """
        return tools["run_sql"](sql=sql)

    def make_chart(kind: str, title: str, x: str, y: str, series: str = "") -> str:
        """Draw a chart from the rows of the MOST RECENT successful run_sql result. Run a query that returns exactly
        the columns to plot first (text labels such as season_label for x, a numeric column for y).

        Args:
            kind: "bar" to compare categories, "line" for change over seasons, "scatter" for two numbers.
            title: A short descriptive chart title.
            x: Column for the horizontal axis.
            y: Numeric column to plot.
            series: Column that splits the data into colored series (for example player), or an empty string.
        """
        return tools["make_chart"](kind=kind, title=title, x=x, y=y, series=series)

    return [get_schema, run_sql, make_chart]


class GeminiBackend:
    name = "gemini"

    def __init__(self, model=None):
        from google import genai

        self.model = model or DEFAULT_MODELS["gemini"]
        self.client = genai.Client(api_key=gemini_api_key())

    def run(self, system, question, tools, max_steps=MAX_TOOL_STEPS):
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=gemini_functions(tools),
            # The SDK runs the function-call loop for us and feeds results back to the model.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=max_steps),
        )
        resp = with_retry(lambda: self.client.models.generate_content(
            model=self.model, contents=question, config=config))
        return (resp.text or "").strip()

    def complete(self, prompt):
        resp = with_retry(lambda: self.client.models.generate_content(model=self.model, contents=prompt))
        return (resp.text or "").strip()


def available_models(provider):
    """Model ids the current API key can use (text-generation models for Gemini)."""
    if provider == "openai":
        from openai import OpenAI

        return sorted(m.id for m in OpenAI().models.list())
    from google import genai

    models = list(genai.Client(api_key=gemini_api_key()).models.list())
    usable = [m for m in models if "generateContent" in (getattr(m, "supported_actions", None) or [])] or models
    return sorted((getattr(m, "name", None) or "").removeprefix("models/") for m in usable)


def pick_best_model(provider, ids):
    """Choose the model to write code with from a list of ids, or None if nothing suitable is listed.

    Only plain base names are considered, which leaves out mini/nano/pro/codex, audio, image and embedding models,
    dated snapshots and '-latest' aliases.
    OpenAI: the newest full-size GPT model (gpt-5.1 beats gpt-5, which beats gpt-4.1).
    Gemini: the newest stable 'flash' model. 'pro' models usually need a paid plan, so use --model for those."""
    pattern = r"gpt-(\d+)(?:\.(\d+))?" if provider == "openai" else r"gemini-(\d+)(?:\.(\d+))?-flash"
    versions = {}
    for model_id in ids:
        match = re.fullmatch(pattern, model_id)
        if match:
            versions[model_id] = (int(match.group(1)), int(match.group(2) or 0))
    return max(versions, key=versions.get) if versions else None


def best_model(provider):
    """Ask the provider which models this key can use and pick one (see pick_best_model)."""
    return pick_best_model(provider, available_models(provider))


BACKENDS = {"openai": OpenAIBackend, "gemini": GeminiBackend}


def make_backend(provider, model=None):
    if provider not in BACKENDS:
        raise ValueError(f"provider must be one of {sorted(BACKENDS)}, got {provider!r}")
    return BACKENDS[provider](model)
