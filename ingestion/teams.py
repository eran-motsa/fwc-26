"""Sync team history (WC 2022 ratings seed), APIF team IDs, and golden boot data.

Uses both football-data.org (WC 2026 squad/scorer data) and API-Football
(WC 2022 historical match data for ratings seed and APIF ID mapping).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db  # noqa: E402
from ingestion.client import get as apif_get  # noqa: E402
from ingestion.fd_client import get as fd_get  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

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


def sync_apif_ids() -> int:
    """Store API-Football team IDs for WC 2026 teams using WC 2022 fixture data.

    26 of 48 WC 2026 teams also played in WC 2022. Their APIF IDs are extracted
    from the 2022 fixture data and stored in teams.apif_id for H2H lookups.
    Costs 1 API-Football call.
    """
    name_to_fd_id = _build_name_index()
    data = apif_get("fixtures", {"league": 1, "season": 2022})

    apif_name_to_id: dict[str, int] = {}
    for item in data.get("response", []):
        for side in ("home", "away"):
            t = item["teams"][side]
            apif_name_to_id[t["name"]] = t["id"]

    conn = get_db()
    n = 0
    for apif_name, apif_id in apif_name_to_id.items():
        fd_name = _APIF_TO_FD.get(apif_name, apif_name)
        fd_id = name_to_fd_id.get(_norm(fd_name))
        if fd_id is None:
            continue  # not a WC 2026 team
        conn.execute("UPDATE teams SET apif_id=? WHERE id=?", (apif_id, fd_id))
        n += 1
    conn.commit()
    conn.close()
    print(f"Stored APIF IDs for {n} WC 2026 teams (from WC 2022 data).")
    return n


# Real bookmaker golden boot odds — seeded from market data, sorted by odds (favourite first).
# Lower decimal odds = more likely to score most goals.
_GOLDEN_BOOT_MARKET: list[tuple] = [
    ("Kylian Mbappé",     "France",        6.5),
    ("Harry Kane",        "England",       7.5),
    ("Lionel Messi",      "Argentina",    13.0),
    ("Mikel Oyarzabal",   "Spain",        13.0),
    ("Erling Haaland",    "Norway",       13.0),
    ("Lamine Yamal",      "Spain",        15.0),
    ("Cristiano Ronaldo", "Portugal",     21.0),
    ("Ousmane Dembélé",   "France",       21.0),
    ("Vinícius Júnior",   "Brazil",       23.0),
    ("Niclas Woltemade",  "Germany",      26.0),
    ("Lautaro Martínez",  "Argentina",    26.0),
    ("Raphinha",          "Brazil",       26.0),
    ("Julián Álvarez",    "Argentina",    29.0),
    ("Romelu Lukaku",     "Belgium",      29.0),
    ("Kai Havertz",       "Germany",      29.0),
    ("Bukayo Saka",       "England",      34.0),
    ("Neymar",            "Brazil",       34.0),
    ("Ferran Torres",     "Spain",        41.0),
    ("Cody Gakpo",        "Netherlands",  41.0),
    ("Jude Bellingham",   "England",      41.0),
    ("Michael Olise",     "France",       41.0),
    ("Mikel Merino",      "Spain",        41.0),
]


def seed_golden_boot_market() -> int:
    """Seed golden boot candidates from real bookmaker odds (pre-tournament market data)."""
    conn = get_db()
    name_to_id = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM teams").fetchall()}
    conn.execute("DELETE FROM golden_boot_candidates WHERE source='market'")
    n = 0
    for rank, (player, team_name, odds) in enumerate(_GOLDEN_BOOT_MARKET, 1):
        team_id = name_to_id.get(team_name, 0)
        conn.execute(
            "INSERT OR REPLACE INTO golden_boot_candidates"
            "(player, team_id, team_name, goals, rank, source, created_at, odds)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (player, team_id, team_name, 0, rank, "market", _now(), odds),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"Seeded {n} golden boot market candidates.")
    return n


def sync_golden_boot() -> int:
    """Seed golden boot contenders from WC 2026 data (football-data.org).

    Uses real WC 2026 goal scorers once the tournament is underway. Pre-tournament
    (or when no goals yet), falls back to squad attackers ranked by team attack
    rating as a proxy for scoring likelihood.
    Costs 1-2 football-data.org API calls.
    """
    conn = get_db()

    # 1. Try real WC 2026 goal scorers
    scorer_data = fd_get("competitions/WC/scorers", {"limit": 20})
    scorers = scorer_data.get("scorers", [])
    if scorers:
        conn.execute("DELETE FROM golden_boot_candidates WHERE source='wc2026'")
        n = 0
        for rank, s in enumerate(scorers, 1):
            conn.execute(
                "INSERT OR REPLACE INTO golden_boot_candidates"
                "(player, team_id, team_name, goals, rank, source, created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (s["player"]["name"], s["team"]["id"], s["team"]["name"],
                 s["numberOfGoals"], rank, "wc2026", _now()),
            )
            n += 1
        conn.commit()
        conn.close()
        print(f"Stored {n} WC 2026 real scorers as golden boot candidates.")
        return n

    # 2. No goals yet — use market-seeded data if available (most realistic)
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM golden_boot_candidates WHERE source='market'"
    ).fetchone()[0]
    conn.close()
    if count > 0:
        print(f"No WC 2026 goals yet. Using {count} market-seeded golden boot candidates.")
        return count

    # 3. Last resort — seed from market list now (first time setup)
    return seed_golden_boot_market()


def sync_recent_national_form(limit_per_team: int = 8) -> int:
    """Pull 2024-season national team fixtures for all 48 WC 2026 teams.

    API-Football season=2024 covers the 2024-2025 international calendar
    (Nations League, qualifiers, continental cups, friendlies). Stores results
    in team_matches so both _recent_form() display and Dixon-Coles ratings improve.
    Costs 1 API call per team (48 calls). Run once during backfill.
    """
    import time
    conn = get_db()
    all_teams = conn.execute(
        "SELECT id, name, apif_id FROM teams WHERE apif_id IS NOT NULL"
    ).fetchall()
    apif_to_fd = {t["apif_id"]: t["id"] for t in all_teams}
    conn.close()

    total = 0
    for team in all_teams:
        time.sleep(6.5)  # respect 10 req/min rate limit
        try:
            data = apif_get("fixtures", {"team": team["apif_id"], "season": 2024, "status": "FT"})
        except Exception as e:
            print(f"  {team['name']}: {e}")
            continue
        matches = sorted(data.get("response", []), key=lambda m: m["fixture"]["date"], reverse=True)
        conn = get_db()
        for item in matches[:limit_per_team]:
            fx_id   = item["fixture"]["id"]
            h_apif  = item["teams"]["home"]["id"]
            a_apif  = item["teams"]["away"]["id"]
            h_goals = item["goals"]["home"]
            a_goals = item["goals"]["away"]
            if h_goals is None or a_goals is None:
                continue
            is_home = (h_apif == team["apif_id"])
            team_fd = apif_to_fd.get(h_apif if is_home else a_apif)
            opp_fd  = apif_to_fd.get(a_apif if is_home else h_apif)
            gf = h_goals if is_home else a_goals
            ga = a_goals if is_home else h_goals
            if team_fd is None:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO team_matches"
                "(fixture_id, team_id, opp_id, goals_for, goals_against, date_utc, is_home)"
                " VALUES(?,?,?,?,?,?,?)",
                (fx_id, team_fd, opp_fd, gf, ga, item["fixture"]["date"], int(is_home)),
            )
            total += 1
        conn.commit()
        conn.close()
        print(f"  {team['name']}: {min(len(matches), limit_per_team)} matches synced")
    print(f"Total recent form rows stored: {total}")
    return total


if __name__ == "__main__":
    sync_team_history()
    sync_apif_ids()
    sync_golden_boot()
