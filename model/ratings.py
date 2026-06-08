"""Fit Dixon-Coles ratings from stored team history and persist them."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db  # noqa: E402
from model.dixon_coles import fit_ratings  # noqa: E402


def _load_matches() -> list[dict]:
    """Reconstruct home/away matches from team_matches (each match stored twice,
    once per team; keep the home-perspective row)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT fixture_id, team_id, opp_id, goals_for, goals_against, is_home "
        "FROM team_matches WHERE is_home=1"
    ).fetchall()
    conn.close()
    return [
        {"home_id": r["team_id"], "away_id": r["opp_id"],
         "hg": r["goals_for"], "ag": r["goals_against"], "weight": 1.0}
        for r in rows
    ]


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
