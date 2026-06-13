"""Fit Dixon-Coles ratings from stored team history and persist them."""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db  # noqa: E402
from model.dixon_coles import fit_ratings  # noqa: E402


_HALF_LIFE_DAYS = 365  # matches decay to 0.5 weight after this many days
_WC2026_BOOST = 2.0   # WC 2026 tournament matches are weighted extra heavily


def _decay_weight(date_utc: str) -> float:
    """Exponential time-decay: recent matches weighted higher than old ones."""
    if not date_utc:
        return 0.3  # unknown date → old data, down-weight
    try:
        match_date = datetime.fromisoformat(date_utc[:10])
        days_ago = (datetime.utcnow() - match_date).days
        return math.exp(-math.log(2) * days_ago / _HALF_LIFE_DAYS)
    except Exception:
        return 0.3


def _load_matches() -> list[dict]:
    """Reconstruct home/away matches from team_matches (each match stored twice,
    once per team; keep the home-perspective row). Recent matches weighted higher."""
    conn = get_db()
    # WC 2026 fixture IDs come from football-data.org (range ~500k-600k)
    # Historical data uses API-Football IDs (range ~800k+)
    # Use this to give WC 2026 matches a boost
    wc2026_ids = {
        r["id"] for r in conn.execute(
            "SELECT id FROM fixtures WHERE status='FT'"
        ).fetchall()
    }
    rows = conn.execute(
        "SELECT fixture_id, team_id, opp_id, goals_for, goals_against, is_home, date_utc "
        "FROM team_matches WHERE is_home=1 AND opp_id IS NOT NULL"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        w = _decay_weight(r["date_utc"])
        if r["fixture_id"] in wc2026_ids:
            w *= _WC2026_BOOST
        result.append({
            "home_id": r["team_id"], "away_id": r["opp_id"],
            "hg": r["goals_for"], "ag": r["goals_against"],
            "weight": round(w, 4),
        })
    return result


def run() -> dict:
    matches = _load_matches()
    if len(matches) < 10:
        print(f"WARNING: only {len(matches)} historical matches — ratings will be weak.")
    params = fit_ratings(matches)
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    for team_id, atk in params["attack"].items():
        dfc = params["defence"][team_id]
        conn.execute(
            "INSERT INTO ratings(team_id, attack, defence, computed_at) "
            "VALUES(?,?,?,?) ON CONFLICT(team_id) DO UPDATE SET "
            "attack=excluded.attack, defence=excluded.defence, "
            "computed_at=excluded.computed_at",
            (team_id, atk, dfc, now),
        )
    conn.execute(
        "INSERT INTO api_meta(key, value) VALUES('home_adv', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(params["home_adv"]),),
    )
    conn.execute(
        "INSERT INTO api_meta(key, value) VALUES('rho', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(params["rho"]),),
    )
    conn.commit()
    conn.close()
    print(f"Fitted ratings for {len(params['attack'])} teams "
          f"(home_adv={params['home_adv']:.3f}, rho={params['rho']:.3f}).")
    return params


if __name__ == "__main__":
    run()
