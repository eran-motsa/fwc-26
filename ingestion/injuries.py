"""Injuries: no free API source is available for WC matches.

API-Football free tier returns 0 results per-fixture even for 2022 WC matches,
and the bulk league+season endpoint is blocked for 2026 on free plans.
These stubs keep the orchestrator imports working; the UI shows N/A for injuries.
"""


def sync_injuries(date_local: str) -> int:
    print(f"Injuries: no free data source for WC — skipped ({date_local}).")
    return 0


def sync_lineups(date_local: str) -> int:
    """Lineups are now handled by ingestion.apif_bridge.sync_lineups."""
    return 0


if __name__ == "__main__":
    from datetime import date
    sync_injuries(date.today().isoformat())
