"""Charts for the agent's answers.

The agent asks for a chart with its `make_chart` tool and chooses the columns; the numbers always come from the
rows of its own SQL result, never from the model's memory. User-interface code turns a ChartSpec into a picture:

    fig = render_chart(spec)      # a matplotlib Figure (gr.Plot(fig) shows it)
    path = to_png(spec)           # a temporary PNG file (gr.Image(path) shows it, and it can be downloaded)
"""
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal

from matplotlib.figure import Figure

KINDS = ("bar", "line", "scatter")
MAX_CHARTS_PER_QUESTION = 3
PALETTE = ["#145DA0", "#D96A1E", "#2E8B57", "#7B4FA3", "#B8860B", "#C2185B", "#37474F", "#00838F"]


@dataclass
class ChartSpec:
    kind: str                # "bar", "line" or "scatter"
    title: str
    x: str                   # column for the horizontal axis (categories for bar and line)
    y: str                   # numeric column to plot
    series: str = ""         # optional column that splits the data into several colored series
    columns: list = field(default_factory=list)   # the SQL result the chart is drawn from
    rows: list = field(default_factory=list)


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


def _pull(spec):
    """Returns (x_values, y_values, series_values) as parallel lists, dropping rows with no number to plot."""
    index = {name: i for i, name in enumerate(spec.columns)}
    for needed in (spec.x, spec.y) + ((spec.series,) if spec.series else ()):
        if needed not in index:
            raise ValueError(f"column '{needed}' is not in the query result {spec.columns}")
    xs, ys, groups = [], [], []
    for row in spec.rows:
        y = _number(row[index[spec.y]])
        if y is None:
            continue
        xs.append(row[index[spec.x]])
        ys.append(y)
        groups.append(row[index[spec.series]] if spec.series else None)
    if not ys:
        raise ValueError(f"column '{spec.y}' has no numbers to plot")
    return xs, ys, groups


def _category_axis(ax, categories, horizontal=False):
    ticks, labels = (ax.set_yticks, ax.set_yticklabels) if horizontal else (ax.set_xticks, ax.set_xticklabels)
    ticks(range(len(categories)))
    crowded = len(categories) > 6 and not horizontal
    if horizontal:
        labels([str(c) for c in categories])
    else:
        labels([str(c) for c in categories], rotation=45 if crowded else 0, ha="right" if crowded else "center")


def render_chart(spec):
    """Draw a ChartSpec and return a matplotlib Figure. Raises ValueError with a plain message if it cannot."""
    if spec.kind not in KINDS:
        raise ValueError(f"chart kind must be one of {KINDS}, not '{spec.kind}'")
    xs, ys, groups = _pull(spec)
    fig = Figure(figsize=(8, 4.5), dpi=150)
    ax = fig.add_subplot(111)

    names = list(dict.fromkeys(groups)) if spec.series else [None]
    categories = list(dict.fromkeys(xs))
    colors = {name: PALETTE[i % len(PALETTE)] for i, name in enumerate(names)}
    label = lambda name: str(name) if name is not None else None
    horizontal = False

    if spec.kind == "scatter":
        xnum = [_number(x) for x in xs]
        if any(v is None for v in xnum):
            raise ValueError(f"a scatter chart needs numbers in '{spec.x}'")
        for name in names:
            pick = [i for i, g in enumerate(groups) if g == name]
            ax.scatter([xnum[i] for i in pick], [ys[i] for i in pick], s=36, alpha=0.85, color=colors[name],
                       label=label(name))
    elif spec.kind == "line":
        for name in names:
            points = {x: y for x, y, g in zip(xs, ys, groups) if g == name}
            ax.plot(range(len(categories)), [points.get(c, float("nan")) for c in categories],
                    marker="o", linewidth=2.2, color=colors[name], label=label(name))
        _category_axis(ax, categories)
    else:  # bar
        horizontal = len(categories) > 8 or max(len(str(c)) for c in categories) > 14
        width = 0.8 / len(names)
        for k, name in enumerate(names):
            points = {x: y for x, y, g in zip(xs, ys, groups) if g == name}
            positions = [i + (k - (len(names) - 1) / 2) * width for i in range(len(categories))]
            heights = [points.get(c, 0) for c in categories]
            draw = ax.barh if horizontal else ax.bar
            draw(positions, heights, width * 0.92 if len(names) > 1 else 0.7, color=colors[name], label=label(name))
        _category_axis(ax, categories, horizontal)
        if horizontal:
            ax.invert_yaxis()

    if horizontal:
        ax.set_xlabel(spec.y)
        ax.set_ylabel(spec.x)
    else:
        ax.set_xlabel(spec.x)
        ax.set_ylabel(spec.y)
    ax.set_title(spec.title or f"{spec.y} by {spec.x}", fontsize=14, fontweight="bold", loc="left")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x" if horizontal else "y", alpha=0.25)
    ax.set_axisbelow(True)
    if spec.series:
        ax.legend(frameon=False, title=spec.series, fontsize=10)
    fig.tight_layout()
    return fig


def to_png(spec):
    """Render the chart to a temporary PNG file and return its path."""
    fig = render_chart(spec)
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    fig.savefig(handle.name, bbox_inches="tight")
    return handle.name
