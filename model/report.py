"""Build the daily snapshot (daily_output) that the UI renders and history keeps.

For each match on the given day it bundles: teams, kickoff, stage, venue,
form, injuries, lineups, model markets, bookmaker consensus, the value edge,
and the optimal exact-score bet under the custom scoring rules.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db  # noqa: E402
from ingestion.apif_bridge import get_h2h_from_cache  # noqa: E402
from model.scoring import get_stage_rule, optimal_bet  # noqa: E402
from model.tournament import golden_boot, simulate_winner  # noqa: E402


def _recent_form(conn, team_id: int, limit: int = 6) -> str:
    # WC 2026 finished matches come first (most relevant, most recent)
    wc26 = conn.execute(
        """SELECT CASE WHEN home_id=? THEN home_goals ELSE away_goals END AS gf,
                  CASE WHEN home_id=? THEN away_goals ELSE home_goals END AS ga
           FROM fixtures WHERE (home_id=? OR away_id=?) AND status='FT'
              AND home_goals IS NOT NULL
           ORDER BY date_utc DESC LIMIT ?""",
        (team_id, team_id, team_id, team_id, limit),
    ).fetchall()
    # Supplement with WC 2022 / historical data if WC 2026 games < limit
    historical = conn.execute(
        "SELECT goals_for AS gf, goals_against AS ga FROM team_matches "
        "WHERE team_id=? ORDER BY date_utc DESC LIMIT ?",
        (team_id, limit),
    ).fetchall()
    combined = list(wc26) + list(historical)
    combined = combined[:limit]
    out = []
    for r in combined:
        gf, ga = r["gf"], r["ga"]
        if gf is None or ga is None:
            continue
        if gf > ga:
            out.append("W")
        elif gf < ga:
            out.append("L")
        else:
            out.append("D")
    return "".join(out) or "—"


def _injuries(conn, fx_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT team_id, player, reason FROM injuries WHERE fixture_id=?",
        (fx_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _lineups(conn, fx_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT team_id, player, pos FROM lineups WHERE fixture_id=? AND is_starter=1",
        (fx_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def build_day(date_local: str) -> dict:
    conn = get_db()
    fixtures = conn.execute(
        "SELECT * FROM fixtures WHERE date_local=? ORDER BY kickoff_local",
        (date_local,),
    ).fetchall()

    matches = []
    for fx in fixtures:
        pred = conn.execute(
            "SELECT * FROM predictions WHERE fixture_id=?", (fx["id"],)
        ).fetchone()
        cons = conn.execute(
            "SELECT * FROM odds_consensus WHERE fixture_id=?", (fx["id"],)
        ).fetchone()

        block = {
            "fixture_id": fx["id"],
            "home": fx["home_name"], "away": fx["away_name"],
            "kickoff_local": fx["kickoff_local"], "stage": fx["round"],
            "venue": fx["venue"], "status": fx["status"],
            "home_goals": fx["home_goals"], "away_goals": fx["away_goals"],
            "form_home": _recent_form(conn, fx["home_id"]),
            "form_away": _recent_form(conn, fx["away_id"]),
            "h2h": get_h2h_from_cache(fx["home_id"], fx["away_id"]),
            "injuries": _injuries(conn, fx["id"]),
            "lineups": _lineups(conn, fx["id"]),
            "model": None, "consensus": None, "value": None, "recommended_bet": None,
        }

        if pred:
            block["model"] = {
                "p_home": pred["p_home"], "p_draw": pred["p_draw"],
                "p_away": pred["p_away"], "exp_home_goals": pred["exp_home_goals"],
                "exp_away_goals": pred["exp_away_goals"],
                "top_scoreline": pred["top_scoreline"],
                "over25": pred["over25"], "btts": pred["btts"],
            }
        if cons:
            block["consensus"] = {
                "cp_home": cons["cp_home"], "cp_draw": cons["cp_draw"],
                "cp_away": cons["cp_away"], "n_books": cons["n_books"],
                "fair_home": cons["fair_home"], "fair_draw": cons["fair_draw"],
                "fair_away": cons["fair_away"],
            }
        if pred and cons:
            # value edge: model prob - market prob per direction
            block["value"] = {
                "home": round(pred["p_home"] - cons["cp_home"], 3),
                "draw": round(pred["p_draw"] - cons["cp_draw"], 3),
                "away": round(pred["p_away"] - cons["cp_away"], 3),
            }
            bonus, mult = get_stage_rule(fx["round"])
            mat = np.array(json.loads(pred["score_matrix_json"]))
            rec = optimal_bet(mat, cons["fair_home"], cons["fair_draw"],
                              cons["fair_away"], bonus, mult)
            rec["stage_bonus"] = bonus
            rec["odds_multiplier"] = mult
            block["recommended_bet"] = rec

        matches.append(block)

    conn.close()

    payload = {
        "date_local": date_local,
        "matches": matches,
        "tournament": {
            "winner": simulate_winner()[:12],
            "golden_boot": golden_boot(),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return payload


def save_day(date_local: str) -> dict:
    payload = build_day(date_local)
    conn = get_db()
    conn.execute(
        "INSERT INTO daily_output(date_local, payload_json, generated_at) "
        "VALUES(?,?,?) ON CONFLICT(date_local) DO UPDATE SET "
        "payload_json=excluded.payload_json, generated_at=excluded.generated_at",
        (date_local, json.dumps(payload, ensure_ascii=False), payload["generated_at"]),
    )
    conn.commit()
    conn.close()
    print(f"Saved daily snapshot for {date_local} "
          f"({len(payload['matches'])} matches).")
    return payload


if __name__ == "__main__":
    from datetime import date
    save_day(date.today().isoformat())
