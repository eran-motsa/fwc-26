"""Match-day bridge: get today's WC fixture IDs from API-Football (free, date
filter works on match day), map them to our football-data.org–keyed fixtures,
then pull lineups per fixture.

API-Football free tier allows fixtures?date=<today> without a season filter.
We filter client-side for league_id=1 (FIFA World Cup) to isolate WC matches.
Lineups?fixture=<apif_id> is confirmed to work on the free tier for WC matches.

Costs: 1 call (date feed) + 1 call/WC match (lineups) ≈ 5 calls/day max.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import WC_LEAGUE_ID, get_db  # noqa: E402
from ingestion.client import get as apif_get  # noqa: E402

# National-team name differences between football-data.org and API-Football.
# Key = API-Football name, value = football-data.org name (what's in our DB).
_APIF_TO_FD: dict[str, str] = {
    "USA": "United States",
    "South Korea": "Korea Republic",
    "IR Iran": "Iran",
    "Ivory Coast": "Côte d'Ivoire",
    "Bosnia": "Bosnia and Herzegovina",
    "N. Macedonia": "North Macedonia",
}


def _norm(name: str) -> str:
    return name.lower().strip()


def _today_wc_apif() -> list[dict]:
    """Return API-Football fixture dicts for today's WC matches."""
    today = date.today().isoformat()
    data = apif_get("fixtures", {"date": today})
    return [f for f in data.get("response", []) if f["league"]["id"] == WC_LEAGUE_ID]


def _find_db_fixture(apif_home: str, apif_away: str, date_local: str, conn) -> int | None:
    """Look up our DB fixture id by team names + date, handling name variants."""
    fd_home = _APIF_TO_FD.get(apif_home, apif_home)
    fd_away = _APIF_TO_FD.get(apif_away, apif_away)
    row = conn.execute(
        "SELECT id FROM fixtures WHERE date_local=? "
        "AND (LOWER(home_name)=? OR LOWER(home_name)=?) "
        "AND (LOWER(away_name)=? OR LOWER(away_name)=?)",
        (
            date_local,
            _norm(apif_home), _norm(fd_home),
            _norm(apif_away), _norm(fd_away),
        ),
    ).fetchone()
    return row["id"] if row else None


def sync_lineups(date_local: str) -> int:
    """Pull and store WC lineups for today. Returns total player rows stored."""
    apif_fixtures = _today_wc_apif()
    if not apif_fixtures:
        print(f"No WC fixtures found in API-Football feed for {date_local}.")
        return 0

    conn = get_db()
    pulled = datetime.now(timezone.utc).isoformat()
    n = 0

    for f in apif_fixtures:
        apif_id = f["fixture"]["id"]
        apif_home = f["teams"]["home"]["name"]
        apif_away = f["teams"]["away"]["name"]

        db_id = _find_db_fixture(apif_home, apif_away, date_local, conn)
        if db_id is None:
            print(f"  Warning: no DB fixture for '{apif_home}' vs '{apif_away}' on {date_local}")
            continue

        # Store APIF fixture id + team APIF IDs (for H2H lookups)
        conn.execute(
            "UPDATE fixtures SET apif_fixture_id=? WHERE id=?", (apif_id, db_id)
        )
        for side in ("home", "away"):
            apif_team_name = f["teams"][side]["name"]
            apif_team_id = f["teams"][side]["id"]
            fd_team_name = _APIF_TO_FD.get(apif_team_name, apif_team_name)
            conn.execute(
                "UPDATE teams SET apif_id=? WHERE LOWER(name)=? AND apif_id IS NULL",
                (apif_team_id, _norm(fd_team_name)),
            )
        conn.commit()  # release write lock before API call opens a second connection

        lineup_data = apif_get("fixtures/lineups", {"fixture": apif_id})
        for team_block in lineup_data.get("response", []):
            apif_team_name = team_block.get("team", {}).get("name", "")
            fd_team_name = _APIF_TO_FD.get(apif_team_name, apif_team_name)
            team_row = conn.execute(
                "SELECT id FROM teams WHERE LOWER(name)=?", (_norm(fd_team_name),)
            ).fetchone()
            team_id = team_row["id"] if team_row else None

            for starter in team_block.get("startXI", []):
                pl = starter.get("player", {})
                conn.execute(
                    "INSERT INTO lineups(fixture_id, team_id, player, pos, is_starter, pulled_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (db_id, team_id, pl.get("name"), pl.get("pos"), 1, pulled),
                )
                n += 1
            for sub in team_block.get("substitutes", []):
                pl = sub.get("player", {})
                conn.execute(
                    "INSERT INTO lineups(fixture_id, team_id, player, pos, is_starter, pulled_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (db_id, team_id, pl.get("name"), pl.get("pos"), 0, pulled),
                )
                n += 1

    conn.commit()
    conn.close()
    print(f"Stored {n} lineup entries for {date_local}.")
    return n


def _fetch_h2h(apif_id1: int, apif_id2: int) -> list[dict]:
    """Call API-Football H2H endpoint and return normalised finished results."""
    data = apif_get("fixtures/headtohead", {"h2h": f"{apif_id1}-{apif_id2}"})
    finished = [
        f for f in data.get("response", [])
        if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")
    ]
    finished.sort(key=lambda f: f["fixture"]["date"], reverse=True)
    results = []
    for f in finished[:10]:
        home = _APIF_TO_FD.get(f["teams"]["home"]["name"], f["teams"]["home"]["name"])
        away = _APIF_TO_FD.get(f["teams"]["away"]["name"], f["teams"]["away"]["name"])
        results.append({
            "date": f["fixture"]["date"][:10],
            "home": home,
            "away": away,
            "home_goals": f["goals"]["home"],
            "away_goals": f["goals"]["away"],
        })
    return results


def get_h2h_from_cache(home_fd_id: int, away_fd_id: int) -> list[dict]:
    """Return cached H2H results for a pair of FD team IDs. Empty if not cached."""
    conn = get_db()
    ids = conn.execute(
        "SELECT apif_id FROM teams WHERE id IN (?,?)", (home_fd_id, away_fd_id)
    ).fetchall()
    conn.close()
    if len(ids) < 2 or any(r["apif_id"] is None for r in ids):
        return []
    k1 = min(ids[0]["apif_id"], ids[1]["apif_id"])
    k2 = max(ids[0]["apif_id"], ids[1]["apif_id"])
    conn = get_db()
    row = conn.execute(
        "SELECT payload_json FROM h2h_cache WHERE team1_apif=? AND team2_apif=?",
        (k1, k2),
    ).fetchone()
    conn.close()
    return json.loads(row["payload_json"])[:5] if row else []


def sync_h2h_for_day(date_local: str) -> int:
    """Fetch and cache H2H for all fixtures on date_local that have APIF IDs.

    Skips pairs already in the cache (H2H history is stable; ~10 calls/day max).
    """
    conn = get_db()
    fixtures = conn.execute(
        "SELECT f.id, t1.apif_id AS home_apif, t2.apif_id AS away_apif "
        "FROM fixtures f "
        "JOIN teams t1 ON t1.id=f.home_id "
        "JOIN teams t2 ON t2.id=f.away_id "
        "WHERE f.date_local=? AND t1.apif_id IS NOT NULL AND t2.apif_id IS NOT NULL",
        (date_local,),
    ).fetchall()
    conn.close()
    n = 0
    for fx in fixtures:
        k1 = min(fx["home_apif"], fx["away_apif"])
        k2 = max(fx["home_apif"], fx["away_apif"])
        conn = get_db()
        already = conn.execute(
            "SELECT 1 FROM h2h_cache WHERE team1_apif=? AND team2_apif=?", (k1, k2)
        ).fetchone()
        conn.close()
        if already:
            continue
        results = _fetch_h2h(fx["home_apif"], fx["away_apif"])
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO h2h_cache(team1_apif,team2_apif,payload_json,fetched_at)"
            " VALUES(?,?,?,?)",
            (k1, k2, json.dumps(results), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
        n += 1
    print(f"Synced H2H for {n} new team pairs on {date_local}.")
    return n


if __name__ == "__main__":
    from zoneinfo import ZoneInfo
    from config import TZ_LOCAL
    today = datetime.now(ZoneInfo(TZ_LOCAL)).strftime("%Y-%m-%d")
    sync_lineups(today)
