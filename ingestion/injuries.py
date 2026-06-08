"""Pull injuries and expected/confirmed lineups for a given day's fixtures."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import WC_LEAGUE_ID, WC_SEASON, get_db  # noqa: E402
from ingestion.client import get  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fixtures_on(date_local: str) -> list[int]:
    conn = get_db()
    rows = conn.execute(
        "SELECT id FROM fixtures WHERE date_local=?", (date_local,)
    ).fetchall()
    conn.close()
    return [r["id"] for r in rows]


def sync_injuries(date_local: str) -> int:
    """Pull tournament injuries once; store those for the day's fixtures."""
    fixture_ids = set(_fixtures_on(date_local))
    if not fixture_ids:
        print(f"No fixtures on {date_local}; skipping injuries.")
        return 0
    data = get("injuries", {"league": WC_LEAGUE_ID, "season": WC_SEASON})
    conn = get_db()
    pulled = _now()
    n = 0
    for item in data.get("response", []):
        fx_id = (item.get("fixture") or {}).get("id")
        if fx_id not in fixture_ids:
            continue
        team = item.get("team", {})
        player = item.get("player", {})
        conn.execute(
            "INSERT INTO injuries(fixture_id, team_id, player, reason, pulled_at) "
            "VALUES(?,?,?,?,?)",
            (fx_id, team.get("id"), player.get("name"),
             player.get("reason"), pulled),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"Stored {n} injuries for {date_local}.")
    return n


def sync_lineups(date_local: str) -> int:
    """Pull lineups for each of the day's fixtures (1 call each)."""
    pulled = _now()
    conn = get_db()
    n = 0
    for fx_id in _fixtures_on(date_local):
        data = get("fixtures/lineups", {"fixture": fx_id})
        for team_block in data.get("response", []):
            team = team_block.get("team", {})
            for p in team_block.get("startXI", []):
                pl = p.get("player", {})
                conn.execute(
                    "INSERT INTO lineups(fixture_id, team_id, player, pos, "
                    "is_starter, pulled_at) VALUES(?,?,?,?,?,?)",
                    (fx_id, team.get("id"), pl.get("name"), pl.get("pos"), 1, pulled),
                )
                n += 1
            for p in team_block.get("substitutes", []):
                pl = p.get("player", {})
                conn.execute(
                    "INSERT INTO lineups(fixture_id, team_id, player, pos, "
                    "is_starter, pulled_at) VALUES(?,?,?,?,?,?)",
                    (fx_id, team.get("id"), pl.get("name"), pl.get("pos"), 0, pulled),
                )
                n += 1
    conn.commit()
    conn.close()
    print(f"Stored {n} lineup entries for {date_local}.")
    return n


if __name__ == "__main__":
    from datetime import date
    sync_injuries(date.today().isoformat())
    sync_lineups(date.today().isoformat())
