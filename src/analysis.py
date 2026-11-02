"""Are Lichess pairings fair, and where should a matchmaker cap the rating gap?

Decision rules, fixed before running:
- A pairing counts as competitive if the lower-rated player's expected score is
  at least 30%. The cap is the first 50-point gap band whose measured underdog
  score has a 95% CI entirely below 30%.
- Flag first-move advantage for review if white's score has a 95% CI above 50%
  and exceeds 50% by at least 1 percentage point in evenly rated games (gap < 50).
"""
import os
import sys

import numpy as np
import pandas as pd
import statsmodels.api as sm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gamestats as gs  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

OUT = os.path.join(HERE, "..", "out")
GAP_EDGES = list(range(0, 501, 50)) + [np.inf]
RATING_BANDS = [(0, 1400, "under 1400"), (1400, 1800, "1400–1799"), (1800, 2200, "1800–2199"), (2200, np.inf, "2200+")]
TARGET = .30


def score_ci(s):
    """Mean score with a normal interval, for wins, draws and losses."""
    m, se = s.mean(), s.std(ddof=1) / np.sqrt(len(s))
    return {"n": int(len(s)), "score": float(m), "ci_low": float(m - 1.96 * se), "ci_high": float(m + 1.96 * se)}


def load():
    raw = pd.read_csv(gs.data_path("lichess_games.csv"))
    assert raw.shape == (20058, 16), "unexpected file"
    assert set(raw["winner"]) == {"white", "black", "draw"}
    d = raw.drop_duplicates("game_id").copy()
    d["white_score"] = d["winner"].map({"white": 1.0, "draw": .5, "black": 0.0})
    d["gap"] = (d["white_rating"] - d["black_rating"]).abs()
    d["signed"] = d["white_rating"] - d["black_rating"]
    d["avg_rating"] = (d["white_rating"] + d["black_rating"]) / 2
    d["underdog_score"] = np.where(d["signed"] > 0, 1 - d["white_score"], d["white_score"])
    return raw, d


def gap_table(d):
    rows = []
    for lo, hi in zip(GAP_EDGES[:-1], GAP_EDGES[1:]):
        g = d[(d.gap >= lo) & (d.gap < hi) & (d.signed != 0)]
        mid = g.gap.mean()
        rows.append({"gap_low": lo, "gap_high": None if hi == np.inf else hi, "elo_expected": float(1 / (1 + 10 ** (mid / 400))),
                     "median_turns": float(g.turns.median()), "share_of_games": len(g) / len(d), **score_ci(g.underdog_score)})
    return rows


def main():
    gs.style()
    raw, d = load()
    rated = d[d.rated]
    facts = {"checks": {"rows": len(raw), "duplicate_game_ids_removed": len(raw) - len(d), "unique_games": len(d), "rated_games": len(rated),
                        "players": int(pd.concat([d.white_id, d.black_id]).nunique())},
             "outcomes": rated["winner"].value_counts(normalize=True).to_dict()}

    # First-move advantage, in evenly rated games and adjusted for the gap.
    even = rated[rated.gap < 50]
    w = score_ci(even.white_score)
    facts["first_move"] = {**w, "flag": bool(w["ci_low"] > .5 and w["score"] - .5 >= .01), "all_games": score_ci(rated.white_score)}
    decided = rated[rated.winner != "draw"]
    res = sm.Logit((decided.winner == "white").astype(int), sm.add_constant(decided.signed / 100)).fit(disp=0)
    facts["first_move"]["rating_points_equivalent"] = float(res.params["const"] / res.params["signed"] * 100)
    facts["first_move"]["log_odds_white"] = float(res.params["const"])
    facts["first_move"]["log_odds_white_p"] = float(res.pvalues["const"])
    facts["first_move"]["by_rating"] = [{"band": l, **score_ci(even[(even.avg_rating >= a) & (even.avg_rating < b)].white_score)} for a, b, l in RATING_BANDS]

    # Rating gap: underdog score, Elo's expectation and the cap.
    tbl = gap_table(rated)
    facts["gap_table"] = tbl
    cap = next((r for r in tbl if r["ci_high"] < TARGET), None)
    facts["cap"] = {"target_underdog_score": TARGET, "first_band_below_target": cap and {k: cap[k] for k in ("gap_low", "gap_high", "score", "ci_low", "ci_high")}}
    limit = cap["gap_low"] if cap else None
    facts["cap"]["rating_points"] = limit
    if limit is not None:
        over = rated[rated.gap >= limit]
        facts["cap"]["share_of_rated_games_over_cap"] = len(over) / len(rated)
        facts["cap"]["under_cap_score"] = score_ci(rated[(rated.gap < limit) & (rated.signed != 0)].underdog_score)
    facts["gap_summary"] = {"median_gap": float(rated.gap.median()), "share_under_100": float((rated.gap < 100).mean()), "share_200_plus": float((rated.gap >= 200).mean()),
                            "rated_median_gap": float(rated.gap.median()), "unrated_median_gap": float(d[~d.rated].gap.median())}

    # Second look: dates, repeat players, other targets, and whether one cap fits everyone.
    dates = pd.to_datetime(rated["start_time"], unit="ms")
    pairs = pd.Series([tuple(sorted(p)) for p in zip(rated.white_id, rated.black_id)], index=rated.index)
    facts["sample"] = {"first_game": str(dates.min().date()), "last_game": str(dates.max().date()), "games_in_repeat_pairings": float(pairs.duplicated(keep=False).mean()),
                       "games_with_1500_rating": float(((rated.white_rating == 1500) | (rated.black_rating == 1500)).mean()), "games_2_turns_or_fewer": int((rated.turns <= 2).sum())}
    def cluster_ci(keys, n=4000, seed=42):
        g = even.groupby(keys)["white_score"].agg(["sum", "count"]).to_numpy()
        rng = np.random.default_rng(seed)
        draws = [(lambda s: s[:, 0].sum() / s[:, 1].sum())(g[rng.integers(0, len(g), len(g))]) for _ in range(n)]
        return [float(x) for x in np.percentile(draws, [2.5, 97.5])]
    facts["first_move"]["ci_clustered_by_white_player"] = cluster_ci(even.white_id)
    facts["first_move"]["ci_clustered_by_pairing"] = cluster_ci(pairs[even.index])
    facts["cap"]["other_targets"] = {str(t_): next((r["gap_low"] for r in tbl if r["ci_high"] < t_), None) for t_ in (.25, .30, .35)}
    clean = rated[(rated.white_rating != 1500) & (rated.black_rating != 1500) & (rated.turns > 5)]
    base_min = rated.time_increment.str.split("+").str[0].astype(int)
    def around_cap(df, label):
        out = {"group": label, "games": len(df), "share_200_plus": float((df.gap >= 200).mean())}
        for lo, name in ((150, "gap_150_199"), (200, "gap_200_249")):
            g = df[(df.gap >= lo) & (df.gap < lo + 50) & (df.signed != 0)]
            out[name] = score_ci(g.underdog_score) if len(g) >= 2 else None
        return out
    facts["cap"]["robustness"] = around_cap(clean, "no 1500 ratings or games of 5 turns or fewer")
    facts["cap"]["by_time_control"] = [around_cap(rated[m], l) for m, l in ((base_min <= 5, "5 minutes or less"), ((base_min > 5) & (base_min <= 10), "6 to 10 minutes"), (base_min > 10, "over 10 minutes"))]
    facts["cap"]["by_rating"] = [around_cap(rated[(rated.avg_rating >= a) & (rated.avg_rating < b)], l) for a, b, l in RATING_BANDS]

    fig, ax = plt.subplots(figsize=(10, 4.2))
    x = np.arange(len(tbl))
    labels = [f"{r['gap_low']}–{r['gap_high'] - 1}" if r["gap_high"] else f"{r['gap_low']}+" for r in tbl]
    ax.errorbar(x, [100 * r["score"] for r in tbl], yerr=[[100 * (r["score"] - r["ci_low"]) for r in tbl], [100 * (r["ci_high"] - r["score"]) for r in tbl]],
                color=gs.SERIES[0], marker="o", ms=6, capsize=3, label="measured underdog score (95% CI)", zorder=3)
    ax.plot(x, [100 * r["elo_expected"] for r in tbl], color=gs.SERIES[1], label="what the Elo formula expects", zorder=2)
    ax.axhline(100 * TARGET, color=gs.MUTED, lw=1)
    ax.text(len(tbl) - 1, 100 * TARGET + 1, "30% target", ha="right", color=gs.INK2, fontsize=9)
    ax.set_xticks(x, labels); ax.tick_params(axis="x", colors=gs.INK2, labelsize=9.5, length=0)
    ax.set_ylim(0, 55); ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0f}%"))
    ax.set_xlabel("rating gap between players"); ax.set_title("Lower-rated player's score by rating gap (rated games)")
    ax.legend(loc="upper right")
    gs.save_fig(fig, OUT, "01_underdog_score_by_gap.png")

    br = facts["first_move"]["by_rating"]
    fig, ax = plt.subplots(figsize=(10, 3.2))
    y = np.arange(len(br))[::-1]
    for yy, r in zip(y, br):
        ax.plot([100 * r["ci_low"], 100 * r["ci_high"]], [yy, yy], color=gs.NEUTRAL, zorder=2)
        ax.scatter(100 * r["score"], yy, s=56, color=gs.NEUTRAL, edgecolor=gs.SURFACE, linewidth=2, zorder=3)
    ax.axvline(50, color=gs.INK2, lw=1)
    ax.set_yticks(y, [r["band"] for r in br]); ax.tick_params(axis="y", colors=gs.INK2)
    ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlabel("white's score in evenly rated games, gap under 50 (95% CI)")
    ax.set_title("First-move advantage by average rating")
    gs.save_fig(fig, OUT, "02_first_move_by_rating.png")
    gs.save_results(facts, OUT)
    return facts


if __name__ == "__main__":
    import json
    print(json.dumps(main(), indent=1, default=float))
