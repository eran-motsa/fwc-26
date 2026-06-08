"""Pull the World Cup schedule and results from football-data.org into SQLite.

football-data.org free tier covers WC 2026 (competition code 'WC').
One call syncs all 104 fixtures; upserts keep results current on daily runs.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import FD_COMP, TZ_LOCAL, WC_SEASON, get_db  # noqa: E402
from ingestion.fd_client import get as fd_get  # noqa: E402

LOCAL = ZoneInfo(TZ_LOCAL)

# football-data.org stage strings → our DB stage labels (match scoring_rules keys)
STAGE_MAP: dict[str, str] = {
    "GROUP_STAGE": "Group Stage",
    "ROUND_OF_32": "Round of 32",
    "ROUND_OF_16": "Round of 16",
    "QUARTER_FINALS": "Quarter-finals",
    "SEMI_FINALS": "Semi-finals",
    "THIRD_PLACE": "3rd Place Final",
    "FINAL": "Final",
}

# football-data.org match status → our short status codes
STATUS_MAP: dict[str, str] = {
    "SCHEDULED": "NS",
    "TIMED": "NS",
    "IN_PLAY": "LIVE",
    "PAUSED": "LIVE",
    "FINISHED": "FT",
    "AWARDED": "FT",
    "CANCELLED": "CANC",
    "POSTPONED": "PST",
    "SUSPENDED": "SUSP",
}


def _to_local(iso_utc: str) -> tuple[str, str]:
    """Return (date_local 'YYYY-MM-DD', kickoff_local 'HH:MM') in TZ_LOCAL."""
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(LOCAL)
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def sync_fixtures() -> int:
    """Pull all WC matches; upsert into fixtures + teams tables. Returns count."""
    data = fd_get(f"competitions/{FD_COMP}/matches", {"season": WC_SEASON})
    conn = get_db()
    n = 0
    for m in data.get("matches", []):
        stage_raw = m.get("stage", "GROUP_STAGE")
        stage = STAGE_MAP.get(stage_raw, stage_raw.replace("_", " ").title())
        group = m.get("group") or ""
        round_str = f"{stage} - {group}" if group else stage

        date_local, kickoff_local = _to_local(m["utcDate"])
        status = STATUS_MAP.get(m.get("status", "SCHEDULED"), "NS")

        ft = (m.get("score") or {}).get("fullTime") or {}
        home_goals = ft.get("home")   # None until played
        away_goals = ft.get("away")

        home = m["homeTeam"]
        away = m["awayTeam"]
        venue_obj = m.get("venue") or {}
        venue = venue_obj.get("name", "") if isinstance(venue_obj, dict) else ""

        conn.execute(
            """INSERT INTO fixtures(
                 id, date_utc, date_local, kickoff_local, stage, round,
                 home_id, away_id, home_name, away_name, venue, status,
                 home_goals, away_goals)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 status=excluded.status,
                 home_goals=excluded.home_goals,
                 away_goals=excluded.away_goals""",
            (
                m["id"], m["utcDate"], date_local, kickoff_local,
                stage, round_str,
                home["id"], away["id"],
                home.get("name", home.get("shortName", "TBD")),
                away.get("name", away.get("shortName", "TBD")),
                venue, status, home_goals, away_goals,
            ),
        )
        for side in (home, away):
            if side.get("id"):
                conn.execute(
                    "INSERT INTO teams(id, name) VALUES(?,?) "
                    "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                    (side["id"], side.get("name", side.get("shortName", "TBD"))),
                )
        n += 1

    conn.commit()
    conn.close()
    print(f"Synced {n} fixtures.")
    return n


if __name__ == "__main__":
    sync_fixtures()
