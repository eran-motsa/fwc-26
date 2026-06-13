"""Custom league scoring engine.

Rules (from the league screenshot + your worked example):
  - You bet an EXACT scoreline for a match.
  - If your predicted DIRECTION (home win / draw / away win) is correct, you earn
    that direction's odds value ('יחסים', the fair decimal odds) × the stage's
    odds_multiplier ('מכפיל יחסים').
  - If your EXACT score is also correct, you additionally earn the stage's
    exact_bonus ('בול').
  - If the direction is wrong, you earn 0.

Worked example (Italy–Turkey, odds home 1.2 / draw 3.2 / away 5.7, bonus 4):
  guess 1-0 IT, actual 2-0 IT  -> direction(home) right, exact wrong -> 1.2
  guess 1-2 TR, actual 1-2 TR  -> direction(away) right, exact right -> 5.7 + 4 = 9.7

Expected points of betting scoreline (h,a):
  EP = P(correct direction of (h,a)) * direction_odds * mult
       + P(exact (h,a)) * exact_bonus
We choose the scoreline that maximises EP, using the model's full score matrix.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db  # noqa: E402


def _direction(h: int, a: int) -> str:
    return "home" if h > a else "away" if a > h else "draw"


def get_stage_rule(stage_round: str) -> tuple[float, float]:
    """Map a fixture's round text to (exact_bonus, odds_multiplier)."""
    conn = get_db()
    rows = conn.execute("SELECT stage, exact_bonus, odds_multiplier FROM scoring_rules").fetchall()
    conn.close()
    text = (stage_round or "").lower()
    # match by keyword
    table = {r["stage"].lower(): (r["exact_bonus"], r["odds_multiplier"]) for r in rows}
    keymap = [
        ("final", "final"), ("3rd", "3rd place final"), ("third", "3rd place final"),
        ("semi", "semi-finals"), ("quarter", "quarter-finals"),
        ("round of 16", "round of 16"), ("16", "round of 16"),
        ("round of 32", "round of 32"), ("32", "round of 32"),
        ("group", "group stage"),
    ]
    for needle, stage_key in keymap:
        if needle in text and stage_key in table:
            return table[stage_key]
    return table.get("group stage", (2.0, 1.0))


def optimal_bet(score_matrix: np.ndarray, fair_home: float, fair_draw: float,
                fair_away: float, exact_bonus: float, mult: float,
                cp_home: float | None = None, cp_draw: float | None = None,
                cp_away: float | None = None) -> dict:
    """Find the exact scoreline maximising expected league points.

    Direction probability uses market consensus (cp_*) when available — the
    collective 40+ bookmakers are more reliable than our sparse model for
    "who wins". The model's score matrix is used for exact-score selection,
    which the market does not price.
    """
    n = score_matrix.shape[0]
    # Model direction probs (kept for value-edge display; not used in EP calc)
    p_home = float(np.tril(score_matrix, -1).sum())
    p_draw = float(np.trace(score_matrix))
    p_away = float(np.triu(score_matrix, 1).sum())
    # Direction probs for EP: prefer market; fall back to model if no odds data
    if cp_home is not None and cp_draw is not None and cp_away is not None:
        p_dir = {"home": cp_home, "draw": cp_draw, "away": cp_away}
    else:
        p_dir = {"home": p_home, "draw": p_draw, "away": p_away}
    odds_dir = {"home": fair_home, "draw": fair_draw, "away": fair_away}

    best = None
    table = []
    for h in range(n):
        for a in range(n):
            d = _direction(h, a)
            p_exact = float(score_matrix[h, a])
            ep = p_dir[d] * odds_dir[d] * mult + p_exact * exact_bonus
            row = {
                "scoreline": f"{h}-{a}", "h": h, "a": a, "direction": d,
                "p_exact": round(p_exact, 4), "direction_odds": odds_dir[d],
                "expected_points": round(ep, 3),
            }
            table.append(row)
            if best is None or ep > best["expected_points"]:
                best = row
    table.sort(key=lambda r: r["expected_points"], reverse=True)
    return {"best": best, "top5": table[:5],
            "p_direction": {k: round(v, 3) for k, v in p_dir.items()}}


def score_bet(pred_h: int, pred_a: int, actual_h: int, actual_a: int,
              fair_home: float, fair_draw: float, fair_away: float,
              exact_bonus: float, mult: float) -> tuple[float, str]:
    """Score a settled bet. Returns (points, result_label)."""
    if _direction(pred_h, pred_a) != _direction(actual_h, actual_a):
        return 0.0, "lost"
    odds = {"home": fair_home, "draw": fair_draw, "away": fair_away}[_direction(pred_h, pred_a)]
    pts = odds * mult
    if pred_h == actual_h and pred_a == actual_a:
        return round(pts + exact_bonus, 2), "won_exact"
    return round(pts, 2), "won_direction"
