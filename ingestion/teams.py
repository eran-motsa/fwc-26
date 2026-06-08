"""Pull WC 2022 match results from API-Football to seed the Dixon-Coles ratings.

API-Football free tier allows historical seasons 2022-2024. One call to
fixtures?league=1&season=2022 returns all 64 matches, covering 26 of the 48
teams in WC 2026. Teams that didn't qualify for 2022 use default ratings.

Uses football-data.org team IDs (our primary key) via name-matching.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db  # noqa: E402
from ingestion.client import get as apif_get  # noqa: E402

# API-Football name → football-data.org name for the few that differ
_APIF_TO_FD: dict[str, str] = {
    "USA": "United States",
}


def _norm(name: str) -> str:
    return name.lower().strip()


def _build_name_index() -> dict[str, int]:
    """Return normalised-name → fd team_id map from the teams table."""
    conn = get_db()
    rows = conn.execute("SELECT id, name FROM teams").fetchall()
    conn.close()
    return {_norm(r["name"]): r["id"] for r in rows}


def sync_team_history(last_n: int = 10) -> int:
    """Pull WC 2022 results and store as team_matches for rating seeding.

    last_n is ignored — we take all 64 WC 2022 matches (covers ≈26 of 48 teams).
    Costs 1 API-Football call.
    """
    name_to_id = _build_name_index()

    data = apif_get("fixtures", {"league": 1, "season": 2022})
    conn = get_db()
    total = 0

    for item in data.get("response", []):
        if item["fixture"]["status"]["short"] != "FT":
            continue
        fx_id = item["fixture"]["id"]
        teams = item["teams"]
        goals = item["goals"]

        for side in ("home", "away"):
            apif_name = teams[side]["name"]
            fd_name = _APIF_TO_FD.get(apif_name, apif_name)
            team_id = name_to_id.get(_norm(fd_name))
            if team_id is None:
                continue  # team not in WC 2026 — skip

            opp_side = "away" if side == "home" else "home"
            opp_name = _APIF_TO_FD.get(teams[opp_side]["name"], teams[opp_side]["name"])
            opp_id = name_to_id.get(_norm(opp_name))  # may be None for non-2026 teams

            is_home = side == "home"
            gf = goals["home"] if is_home else goals["away"]
            ga = goals["away"] if is_home else goals["home"]

            conn.execute(
                """INSERT OR IGNORE INTO team_matches(
                     fixture_id, team_id, opp_id, goals_for, goals_against,
                     date_utc, is_home)
                   VALUES(?,?,?,?,?,?,?)""",
                (fx_id, team_id, opp_id, gf, ga,
                 item["fixture"]["date"], int(is_home)),
            )
            total += 1

    conn.commit()
    conn.close()
    print(f"Stored {total} historical team matches (WC 2022 via API-Football).")
    return total


if __name__ == "__main__":
    sync_team_history()
