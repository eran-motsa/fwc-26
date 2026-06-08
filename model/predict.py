"""Compute model predictions for fixtures and store them."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db  # noqa: E402
from model.dixon_coles import derive_markets, score_matrix  # noqa: E402


def _ratings_lookup():
    conn = get_db()
    rows = conn.execute("SELECT team_id, attack, defence FROM ratings").fetchall()
    meta = dict(conn.execute(
        "SELECT key, value FROM api_meta WHERE key IN ('home_adv','rho')").fetchall())
    conn.close()
    r = {row["team_id"]: (row["attack"], row["defence"]) for row in rows}
    return r, float(meta.get("home_adv", 0.25)), float(meta.get("rho", -0.1))


def predict_day(date_local: str) -> int:
    ratings, home_adv, rho = _ratings_lookup()
    conn = get_db()
    fixtures = conn.execute(
        "SELECT id, home_id, away_id FROM fixtures WHERE date_local=?",
        (date_local,),
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for fx in fixtures:
        # Default (0.0, 0.0) = average attack/defence for teams with no history yet
        atk_h, dfc_h = ratings.get(fx["home_id"], (0.0, 0.0))
        atk_a, dfc_a = ratings.get(fx["away_id"], (0.0, 0.0))
        mat = score_matrix(atk_h, dfc_h, atk_a, dfc_a, home_adv, rho)
        mk = derive_markets(mat)
        conn.execute(
            """INSERT INTO predictions(
                 fixture_id, p_home, p_draw, p_away, exp_home_goals,
                 exp_away_goals, top_scoreline, over25, btts,
                 score_matrix_json, computed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(fixture_id) DO UPDATE SET
                 p_home=excluded.p_home, p_draw=excluded.p_draw,
                 p_away=excluded.p_away, exp_home_goals=excluded.exp_home_goals,
                 exp_away_goals=excluded.exp_away_goals,
                 top_scoreline=excluded.top_scoreline, over25=excluded.over25,
                 btts=excluded.btts, score_matrix_json=excluded.score_matrix_json,
                 computed_at=excluded.computed_at""",
            (fx["id"], round(mk["p_home"], 4), round(mk["p_draw"], 4),
             round(mk["p_away"], 4), mk["exp_home_goals"], mk["exp_away_goals"],
             mk["top_scoreline"], mk["over25"], mk["btts"],
             json.dumps(mat.tolist()), now),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"Predicted {n} fixtures for {date_local}.")
    return n


if __name__ == "__main__":
    from datetime import date
    predict_day(date.today().isoformat())
