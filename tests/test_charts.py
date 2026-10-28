"""The chart tool and the chart renderer (no keys, no network)."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from agent import NBAAgent  # noqa: E402
from charts import ChartSpec, render_chart, to_png  # noqa: E402
from db import NBADatabase  # noqa: E402
from make_fixture import make  # noqa: E402

ROWS = [("2022-23", 25.0, "A"), ("2023-24", 27.5, "A"), ("2022-23", 20.0, "B"), ("2023-24", None, "B")]
COLS = ["season_label", "ppg", "player"]


def spec(kind="line", **kw):
    base = dict(kind=kind, title="T", x="season_label", y="ppg", series="player", columns=COLS, rows=ROWS)
    base.update(kw)
    return ChartSpec(**base)


@pytest.mark.parametrize("kind", ["bar", "line"])
def test_renders_each_kind_with_series_and_missing_values(kind):
    fig = render_chart(spec(kind))
    assert fig.axes[0].get_title(loc="left") == "T" and fig.axes[0].get_legend() is not None


def test_scatter_needs_numeric_x():
    fig = render_chart(ChartSpec("scatter", "S", "n", "ppg", columns=["n", "ppg"], rows=[(1, 2.0), (2, 3.5)]))
    assert len(fig.axes[0].collections) == 1
    with pytest.raises(ValueError, match="numbers"):
        render_chart(spec("scatter", series=""))


def test_many_or_long_categories_use_horizontal_bars():
    rows = [(f"A Long Player Name {i}", float(30 - i)) for i in range(12)]
    fig = render_chart(ChartSpec("bar", "Top", "player", "ppg", columns=["player", "ppg"], rows=rows))
    assert fig.axes[0].get_xlabel() == "ppg"


@pytest.mark.parametrize("bad, message", [
    (dict(kind="pie"), "kind must be"),
    (dict(y="nope"), "not in the query result"),
    (dict(y="player", series=""), "no numbers"),
    (dict(rows=[]), "no numbers"),
])
def test_unrenderable_charts_raise_plain_errors(bad, message):
    with pytest.raises(ValueError, match=message):
        render_chart(spec(**bad))


def test_to_png_writes_a_real_png():
    path = Path(to_png(spec("bar")))
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    path.unlink()


class ScriptedBackend:
    """Stands in for OpenAI/Gemini: runs a fixed list of (tool, kwargs) calls and records each tool's reply."""
    name, model = "fake", "fake-1"

    def __init__(self, calls):
        self.calls, self.replies, self.questions = calls, [], []

    def run(self, system, question, tools):
        self.questions.append(question)
        for tool, kwargs in self.calls:
            self.replies.append(tools[tool](**kwargs))
        return "Here is the chart."


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return NBADatabase(make(tmp_path_factory.mktemp("fake_nba")))


SQL = "SELECT season_label, ppg FROM player_season WHERE player = 'Luka Dončić' ORDER BY season"


def test_agent_records_a_chart_from_the_last_query(db):
    backend = ScriptedBackend([("run_sql", {"sql": SQL}),
                               ("make_chart", dict(kind="bar", title="Luka", x="season_label", y="ppg", series=""))])
    result = NBAAgent(db, backend=backend).ask("Chart Luka's scoring")
    assert "Chart created" in backend.replies[1]
    assert len(result.charts) == 1 and result.charts[0].rows == [("2023-24", 33.9), ("2024-25", 28.2)]
    assert result.charts[0].columns == ["season_label", "ppg"]
    render_chart(result.charts[0])


@pytest.mark.parametrize("calls, fragment", [
    ([("make_chart", dict(kind="bar", title="t", x="a", y="b", series=""))], "Run a query"),
    ([("run_sql", {"sql": SQL}), ("make_chart", dict(kind="pie", title="t", x="season_label", y="ppg", series=""))],
     "Unknown chart kind"),
    ([("run_sql", {"sql": SQL}), ("make_chart", dict(kind="bar", title="t", x="season_label", y="oops", series=""))],
     "not in the last query result"),
    ([("run_sql", {"sql": "SELECT season_label FROM player_season"}),
      ("make_chart", dict(kind="bar", title="t", x="season_label", y="season_label", series=""))], "no numbers"),
])
def test_bad_chart_requests_are_explained_to_the_model_and_not_recorded(db, calls, fragment):
    backend = ScriptedBackend(calls)
    result = NBAAgent(db, backend=backend).ask("x")
    assert fragment in backend.replies[-1] and result.charts == []


def test_chart_count_is_capped_and_reset_between_questions(db):
    ok = ("make_chart", dict(kind="bar", title="t", x="season_label", y="ppg", series=""))
    backend = ScriptedBackend([("run_sql", {"sql": SQL})] + [ok] * 4)
    agent = NBAAgent(db, backend=backend)
    assert len(agent.ask("x").charts) == 3 and "limit" in backend.replies[-1]
    backend.calls = [("run_sql", {"sql": SQL}), ok]
    assert len(agent.ask("y").charts) == 1  # a new question starts clean


def test_want_chart_adds_the_request_to_the_question(db):
    backend = ScriptedBackend([])
    agent = NBAAgent(db, backend=backend)
    agent.ask("plain question")
    agent.ask("another", want_chart=True)
    assert backend.questions[0] == "plain question" and "make_chart" in backend.questions[1]


def test_system_prompt_tells_the_agent_how_to_chart(db):
    assert "make_chart" in NBAAgent(db, backend=ScriptedBackend([])).system
