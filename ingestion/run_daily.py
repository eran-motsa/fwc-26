"""16:00 Asia/Jerusalem job: pull today's data (fixtures, injuries, lineups, odds)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TZ_LOCAL, require_keys  # noqa: E402
from ingestion import fixtures, injuries, odds  # noqa: E402


def main() -> None:
    require_keys()
    today = datetime.now(ZoneInfo(TZ_LOCAL)).date().isoformat()
    print(f"=== Ingestion for {today} ===")
    fixtures.sync_fixtures()          # refresh schedule + yesterday's results
    injuries.sync_injuries(today)
    injuries.sync_lineups(today)
    odds.sync_match_odds(today)
    odds.sync_outrights()
    print("Ingestion complete.")


if __name__ == "__main__":
    main()
