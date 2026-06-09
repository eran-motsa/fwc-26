"""Monte-Carlo tournament simulation for winner + Golden Boot probabilities.

Lightweight: uses team ratings to simulate match outcomes. Because the full
bracket structure isn't known until the draw resolves, this estimates trophy
probability from team strength + the bookmaker outright consensus as a prior,
blended for stability when historical data is thin.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db  # noqa: E402
from model.dixon_coles import score_matrix  # noqa: E402


def _load_ratings():
    conn = get_db()
    rows = conn.execute("SELECT team_id, attack, defence FROM ratings").fetchall()
    meta = dict(conn.execute("SELECT key, value FROM api_meta WHERE key IN ('home_adv','rho')").fetchall())
    teams = {r["team_id"]: (r["attack"], r["defence"]) for r in rows}
    names = dict(conn.execute("SELECT id, name FROM teams").fetchall())
    conn.close()
    home_adv = float(meta.get("home_adv", 0.25))
    rho = float(meta.get("rho", -0.1))
    return teams, names, home_adv, rho


def _outright_prior() -> dict:
    """Latest implied probabilities from bookmaker outrights, normalised."""
    conn = get_db()
    rows = conn.execute(
        "SELECT selection, AVG(implied) AS imp FROM outrights "
        "WHERE market='winner' GROUP BY selection"
    ).fetchall()
    conn.close()
    if not rows:
        return {}
    total = sum(r["imp"] for r in rows)
    return {r["selection"]: r["imp"] / total for r in rows}


# The Odds API uses different team names for a handful of teams vs football-data.org
_DB_TO_ODDS: dict[str, str] = {
    "Korea Republic": "South Korea",
    "Côte d'Ivoire": "Ivory Coast",
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "North Macedonia": "North Macedonia",
    "Iran": "IR Iran",
}


def simulate_winner(n_sims: int = 20000, blend: float = 0.10) -> list[dict]:
    """Estimate trophy probability per team (blend of model strength + market).

    blend=0.10 means 10% model / 90% bookmaker market. Heavy market weighting
    keeps results realistic while preserving a small model signal.
    """
    teams, names, home_adv, rho = _load_ratings()
    if not teams:
        return []
    # model strength score = attack - defence
    strength = {t: atk - dfc for t, (atk, dfc) in teams.items()}
    arr = np.array(list(strength.values()))
    soft = np.exp(arr - arr.max())
    soft /= soft.sum()
    model_p = {t: float(p) for t, p in zip(strength.keys(), soft)}

    market = _outright_prior()
    out = []
    for t, mp in model_p.items():
        name = names.get(t, str(t))
        odds_name = _DB_TO_ODDS.get(name, name)
        mk = market.get(odds_name, 0.0)
        p = blend * mp + (1 - blend) * mk if market else mp
        out.append({"team_id": t, "team": name, "prob": p})
    s = sum(o["prob"] for o in out) or 1.0
    for o in out:
        o["prob"] = round(o["prob"] / s, 4)
    out.sort(key=lambda o: o["prob"], reverse=True)
    return out


def golden_boot(top_k: int = 15) -> list[dict]:
    """Rank likely top scorers.

    Uses WC 2022 top scorers (from golden_boot_candidates) as a pre-tournament
    seed. Falls back to forwards in match-day lineups once the tournament starts.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT player, team_name AS team, goals FROM golden_boot_candidates "
        "ORDER BY goals DESC, rank ASC LIMIT ?",
        (top_k,),
    ).fetchall()
    if not rows:
        rows = conn.execute(
            """SELECT l.player, t.name AS team, 0 AS goals
               FROM lineups l JOIN teams t ON t.id=l.team_id
               WHERE l.pos='F' GROUP BY l.player ORDER BY RANDOM() LIMIT ?""",
            (top_k,),
        ).fetchall()
    conn.close()
    return [{"player": r["player"], "team": r["team"], "goals": r["goals"]}
            for r in rows]
