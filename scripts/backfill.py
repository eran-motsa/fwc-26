"""Backfill on first run: fixtures, team history, ratings, and a snapshot for
every match day so the UI has history + accessible future placeholders.

Respects API limits: team history is the heavy part (1 call/team), so it runs
once. Match odds/injuries/lineups for *future* days are intentionally NOT pulled
here — they fill in on each day's 16:00 job, as required.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db, require_keys  # noqa: E402
from ingestion import apif_bridge, fixtures, teams  # noqa: E402
from model import predict, ratings, report  # noqa: E402


def main() -> None:
    require_keys()
    print("▶ Syncing fixtures…")
    fixtures.sync_fixtures()

    print("▶ Pulling team history (qualifiers/friendlies) for ratings seed…")
    teams.sync_team_history(last_n=10)

    print("▶ Syncing APIF team IDs (for H2H lookups)…")
    teams.sync_apif_ids()

    print("▶ Pulling 2024-season national team form (48 teams × ~8 matches)…")
    teams.sync_recent_national_form()

    print("▶ Syncing golden boot contenders (WC 2026)…")
    teams.sync_golden_boot()

    print("▶ Fitting ratings…")
    ratings.run()

    # Build a snapshot for every day that has fixtures. Past/finished days get
    # whatever data exists; future days become accessible placeholders that the
    # daily jobs will enrich.
    conn = get_db()
    dates = [r["date_local"] for r in conn.execute(
        "SELECT DISTINCT date_local FROM fixtures ORDER BY date_local").fetchall()]
    conn.close()

    print("▶ Syncing H2H for first 7 days of group stage matches…")
    for d in dates[:12]:  # covers ~first week, where APIF IDs are known
        apif_bridge.sync_h2h_for_day(d)

    print(f"▶ Generating predictions + snapshots for {len(dates)} match days…")
    for d in dates:
        predict.predict_day(d)
        report.save_day(d)

    print("✅ Backfill complete.")


if __name__ == "__main__":
    main()
