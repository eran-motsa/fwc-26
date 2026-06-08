"""The Odds API v4 client (bookmaker odds for the World Cup)."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ODDS_API_BASE, ODDS_API_KEY, ODDS_REGIONS, ODDS_SPORT_KEY  # noqa: E402


def get_odds(markets: str = "h2h,totals", regions: str | None = None) -> list[dict]:
    """Fetch per-match odds for the World Cup. Returns list of events."""
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": regions or ODDS_REGIONS,
        "markets": markets,
        "oddsFormat": "decimal",
    }
    url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/odds"
    resp = httpx.get(url, params=params, timeout=30)
    resp.raise_for_status()
    _log_credits(resp)
    return resp.json()


def get_outrights(regions: str | None = None) -> list[dict]:
    """Fetch tournament outright markets (winner, etc.)."""
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": regions or ODDS_REGIONS,
        "markets": "outrights",
        "oddsFormat": "decimal",
    }
    url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/odds"
    resp = httpx.get(url, params=params, timeout=30)
    resp.raise_for_status()
    _log_credits(resp)
    return resp.json()


def _log_credits(resp: httpx.Response) -> None:
    used = resp.headers.get("x-requests-used")
    remaining = resp.headers.get("x-requests-remaining")
    if remaining is not None:
        print(f"  Odds API credits: used={used} remaining={remaining}")


def self_test() -> None:
    """Confirm the Odds API key works (counts as 1+ credit)."""
    events = get_odds(markets="h2h")
    print(f"Odds API connectivity OK — {len(events)} World Cup events returned.")


if __name__ == "__main__":
    self_test()
