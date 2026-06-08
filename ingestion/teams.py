"""Pull each World-Cup team's recent matches (qualifiers + friendlies) to seed
the model's attack/defence ratings. Needed because in-tournament coverage is
empty until the tournament starts."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db  # noqa: E402
from ingestion.client import get  # noqa: E402


def _wc_team_ids() -> list[int]:
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT id FROM teams").fetchall()
    conn.close()
    return [r["id"] for r in rows]


def sync_team_history(last_n: int = 10) -> int:
    """For each team, pull last N completed matches and store goals for/against.

    Costs one API call per team — run sparingly (once pre-tournament is enough).
    """
    conn = get_db()
    total = 0
    for team_id in _wc_team_ids():
        data = get("fixtures", {"team": team_id, "last": last_n})
        for item in data.get("response", []):
            fx = item["fixture"]
            if fx["status"]["short"] != "FT":
                continue
            teams = item["teams"]
            goals = item["goals"]
            is_home = teams["home"]["id"] == team_id
            gf = goals["home"] if is_home else goals["away"]
            ga = goals["away"] if is_home else goals["home"]
            opp = teams["away"]["id"] if is_home else teams["home"]["id"]
            conn.execute(
                """INSERT INTO team_matches(
                     fixture_id, team_id, opp_id, goals_for, goals_against,
                     date_utc, is_home)
                   VALUES(?,?,?,?,?,?,?)""",
                (fx["id"], team_id, opp, gf, ga, fx["date"], int(is_home)),
            )
            total += 1
    conn.commit()
    conn.close()
    print(f"Stored {total} historical team matches.")
    return total


if __name__ == "__main__":
    sync_team_history()
