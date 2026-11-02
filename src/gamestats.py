"""Statistics helpers and chart style for this case study."""
from __future__ import annotations

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import stats  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SERIES = ["#2a78d6", "#eb6834", "#6250d6", "#1a9a7b"]
NEUTRAL = "#6250d6"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"


def data_path(name: str) -> str:
    return os.path.join(REPO, "data", name)


def style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": "#c3c2b7",
        "axes.labelcolor": INK2, "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": False, "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID,
        "grid.linewidth": 1, "axes.axisbelow": True, "xtick.color": MUTED, "ytick.color": MUTED,
        "ytick.left": False, "text.color": INK, "font.size": 10.5, "axes.titlesize": 11.5,
        "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False,
        "lines.linewidth": 2, "lines.solid_capstyle": "round",
    })


def save_fig(fig, out_dir: str, name: str) -> None:
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, name), dpi=150, bbox_inches="tight")
    plt.close(fig)


def save_results(facts: dict, out_dir: str) -> None:
    def clean(o):
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.floating, np.integer, np.bool_)):
            return o.item()
        return o
    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(clean(facts), f, indent=2)


def wilson(x: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson interval for a single rate."""
    z = stats.norm.ppf(1 - alpha / 2)
    p = x / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return float(centre - half), float(centre + half)


def rate(x: int, n: int) -> dict:
    lo, hi = wilson(x, n)
    return {"x": int(x), "n": int(n), "rate": x / n, "ci_low": lo, "ci_high": hi}


def bootstrap_stat(values, fn=np.median, n_boot: int = 5_000, seed: int = 42) -> dict:
    """Percentile bootstrap interval for a statistic of one sample."""
    v = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    draws = np.array([fn(v[rng.integers(0, len(v), len(v))]) for _ in range(n_boot)])
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"n": int(len(v)), "value": float(fn(v)), "ci_low": float(lo), "ci_high": float(hi)}


def gini(values) -> float:
    v = np.sort(np.asarray(values, dtype=float))
    n = len(v)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(v) / (n * v.sum()))


def top_share(values, top: float) -> float:
    v = np.sort(np.asarray(values, dtype=float))[::-1]
    k = max(1, int(round(len(v) * top)))
    return float(v[:k].sum() / v.sum())
