"""11:00 Asia/Jerusalem job: update yesterday's results and settle my bets.

Pulls final scores for the previous day's fixtures, compares them against my
recorded bets (and the recommended scoreline), and writes points_awarded +
result into the bets table using the custom scoring engine.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TZ_LOCAL, get_db, require_keys  # noqa: E402
from ingestion import fixtures  # noqa: E402
from model.scoring import get_stage_rule, score_bet  # noqa: E402


def settle(date_local: str) -> int:
    """Settle all pending exact-score bets for fixtures on date_local."""
    conn = get_db()
    pending = conn.execute(
        """SELECT b.*, f.home_goals, f.away_goals, f.status, f.round
           FROM bets b JOIN fixtures f ON f.id=b.fixture_id
           WHERE b.date_local=? AND b.result='pending' AND b.market='exact'""",
        (date_local,),
    ).fetchall()
    settled = 0
    for b in pending:
        if b["status"] != "FT" or b["home_goals"] is None:
            continue  # not finished yet
        cons = conn.execute(
            "SELECT fair_home, fair_draw, fair_away FROM odds_consensus "
            "WHERE fixture_id=?", (b["fixture_id"],),
        ).fetchone()
        if not cons:
            continue
        bonus, mult = get_stage_rule(b["round"])
        pts, label = score_bet(
            b["predicted_home"], b["predicted_away"],
            b["home_goals"], b["away_goals"],
            cons["fair_home"], cons["fair_draw"], cons["fair_away"],
            bonus, mult,
        )
        conn.execute(
            "UPDATE bets SET result=?, points_awarded=? WHERE id=?",
            (label, pts, b["id"]),
        )
        settled += 1
    conn.commit()
    conn.close()
    print(f"Settled {settled} bets for {date_local}.")
    return settled


def store_wc2026_results() -> int:
    """Insert finished WC 2026 matches into team_matches so ratings improve each day."""
    conn = get_db()
    finished = conn.execute(
        "SELECT id, home_id, away_id, home_goals, away_goals, date_utc "
        "FROM fixtures WHERE status='FT' AND home_goals IS NOT NULL "
        "AND home_id IS NOT NULL AND away_id IS NOT NULL"
    ).fetchall()
    n = 0
    for f in finished:
        for is_home, team_id, opp_id, gf, ga in [
            (1, f["home_id"], f["away_id"], f["home_goals"], f["away_goals"]),
            (0, f["away_id"], f["home_id"], f["away_goals"], f["home_goals"]),
        ]:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO team_matches"
                    "(fixture_id, team_id, opp_id, goals_for, goals_against, date_utc, is_home)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (f["id"], team_id, opp_id, gf, ga, f["date_utc"] or "", is_home),
                )
                n += conn.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass
    conn.commit()
    conn.close()
    print(f"Stored {n} new WC 2026 match rows in team_matches.")
    return n


def main() -> None:
    require_keys()
    now = datetime.now(ZoneInfo(TZ_LOCAL))
    yesterday = (now - timedelta(days=1)).date().isoformat()
    today = now.date().isoformat()
    print(f"=== Results + settlement for {yesterday} / {today} ===")
    fixtures.sync_fixtures()   # refresh to capture final scores
    settle(yesterday)
    settle(today)              # also settle today's early kickoffs (e.g. 05:00 games)
    store_wc2026_results()     # feed finished WC 2026 games into ratings training data
    print("Settlement complete.")


if __name__ == "__main__":
    main()
