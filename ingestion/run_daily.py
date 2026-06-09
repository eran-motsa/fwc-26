"""16:00 Asia/Jerusalem job: pull today's data (fixtures, lineups, odds).

Data sources:
  fixtures  — football-data.org (free, covers WC 2026)
  lineups   — API-Football free (date feed → fixture IDs → lineups per match)
  injuries  — no free source; skipped
  odds      — The Odds API (free tier)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TZ_LOCAL, require_keys  # noqa: E402
from ingestion import apif_bridge, fixtures, injuries, odds  # noqa: E402


def main() -> None:
    require_keys()
    today = datetime.now(ZoneInfo(TZ_LOCAL)).strftime("%Y-%m-%d")
    print(f"=== Ingestion for {today} ===")
    fixtures.sync_fixtures()                # refresh schedule + results (football-data.org)
    injuries.sync_injuries(today)           # no-op — no free source
    apif_bridge.sync_lineups(today)         # starting XIs via API-Football free date feed
    apif_bridge.sync_h2h_for_day(today)     # H2H for today's matches (cached, ~N calls)
    odds.sync_match_odds(today)
    odds.sync_outrights()
    print("Ingestion complete.")


if __name__ == "__main__":
    main()
