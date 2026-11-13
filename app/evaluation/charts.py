"""Phase 7: report charts (matplotlib, saved as PNG to docs/charts/).

Style: one hue for single-series charts, thin bars with value labels, light grid, labelled axes.
Colours: series 1 = #2a78d6 (blue), series 2 = #eb6834 (orange) - checked for colour-blind safety.
"""
import math
from pathlib import Path
from typing import Optional

SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"
INK = "#2b2b2b"
MUTED = "#6b6b6b"
GRID = "#e4e4e0"
SURFACE = "#fcfcfb"


def _setup():
    import matplotlib

    matplotlib.use("Agg")  # no screen needed
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK,
        "xtick.color": INK, "ytick.color": MUTED, "axes.titleweight": "bold", "axes.titlesize": 13,
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    })
    return plt


def _style(ax, ylabel: str, title: str, ymax: Optional[float] = None):
    from app.config import settings

    if settings.LLM_PROVIDER == "mock":  # never let pipeline-test charts pass as real results
        title += "  [MOCK DATA - not real results]"
    ax.set_title(title, loc="left", color=INK, pad=12)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    if ymax is not None:
        ax.set_ylim(0, ymax)


def _label_bars(ax, bars, fmt="{:.1f}"):
    for bar in bars:
        h = bar.get_height()
        if not math.isnan(h):  # missing values have no label
            ax.annotate(fmt.format(h), (bar.get_x() + bar.get_width() / 2, h), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", fontsize=10, color=INK)


def bar_chart(path: Path, labels: list[str], values: list[Optional[float]], ylabel: str, title: str,
              ymax: Optional[float] = None, fmt: str = "{:.1f}", threshold: Optional[float] = None,
              threshold_label: str = "") -> Path:
    plt = _setup()
    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=150)
    vals = [float("nan") if v is None else v for v in values]
    bars = ax.bar(labels, vals, color=SERIES_1, width=0.55, edgecolor=SURFACE, linewidth=2)
    _label_bars(ax, bars, fmt)
    if threshold is not None:
        ax.axhline(threshold, color=MUTED, linewidth=1, linestyle="--")
        ax.annotate(threshold_label, (-0.45, threshold), xytext=(0, 4), textcoords="offset points",
                    ha="left", fontsize=9, color=MUTED)
    _style(ax, ylabel, title, ymax)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def grouped_bar_chart(path: Path, labels: list[str], series: dict[str, list[Optional[float]]], ylabel: str,
                      title: str, fmt: str = "{:.1f}") -> Path:
    """Two series side by side (e.g. issues in the first draft vs the final plan)."""
    plt = _setup()
    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=150)
    width = 0.36
    xs = list(range(len(labels)))
    for i, (name, values) in enumerate(series.items()):
        vals = [float("nan") if v is None else v for v in values]
        offset = (i - (len(series) - 1) / 2) * (width + 0.02)
        bars = ax.bar([x + offset for x in xs], vals, width=width, label=name,
                      color=[SERIES_1, SERIES_2][i % 2], edgecolor=SURFACE, linewidth=2)
        _label_bars(ax, bars, fmt)
    ax.set_xticks(xs, labels)
    ax.legend(frameon=False, loc="upper right")
    _style(ax, ylabel, title)
    ax.set_ylim(0, max(1.0, ax.get_ylim()[1] * 1.15))
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
