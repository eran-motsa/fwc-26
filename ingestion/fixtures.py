"""Pull the World Cup schedule and results into SQLite."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TZ_LOCAL, WC_LEAGUE_ID, WC_SEASON, get_db  # noqa: E402
from ingestion.client import get  # noqa: E402

LOCAL = ZoneInfo(TZ_LOCAL)


def _to_local(iso_utc: str) -> tuple[str, str]:
    """Return (date_local 'YYYY-MM-DD', kickoff_local 'HH:MM')."""
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(LOCAL)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def sync_fixtures() -> int:
    """Pull all 104 fixtures; upsert into the fixtures table."""
    data = get("fixtures", {"league": WC_LEAGUE_ID, "season": WC_SEASON})
    conn = get_db()
    n = 0
    for item in data.get("response", []):
        fx = item["fixture"]
        league = item["league"]
        teams = item["teams"]
        goals = item["goals"]
        date_local, kickoff_local = _to_local(fx["date"])
        conn.execute(
            """INSERT INTO fixtures(
                 id, date_utc, date_local, kickoff_local, stage, round,
                 home_id, away_id, home_name, away_name, venue, status,
                 home_goals, away_goals)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 status=excluded.status, home_goals=excluded.home_goals,
                 away_goals=excluded.away_goals, round=excluded.round""",
            (
                fx["id"], fx["date"], date_local, kickoff_local,
                league.get("round", ""), league.get("round", ""),
                teams["home"]["id"], teams["away"]["id"],
                teams["home"]["name"], teams["away"]["name"],
                (fx.get("venue") or {}).get("name", ""),
                fx["status"]["short"], goals["home"], goals["away"],
            ),
        )
        # upsert teams too
        for side in ("home", "away"):
            t = teams[side]
            conn.execute(
                "INSERT INTO teams(id, name) VALUES(?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                (t["id"], t["name"]),
            )
        n += 1
    conn.commit()
    conn.close()
    print(f"Synced {n} fixtures.")
    return n


if __name__ == "__main__":
    sync_fixtures()
