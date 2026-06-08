"""football-data.org v4 HTTP client — free tier (10 req/min, no daily cap).

WC 2026 competition is included on the free tier.
Authentication: X-Auth-Token header with your free key from football-data.org.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import FD_BASE, FD_COMP, FD_KEY  # noqa: E402


def get(path: str, params: dict | None = None) -> dict:
    """GET a football-data.org v4 endpoint. Raises on HTTP errors."""
    headers = {"X-Auth-Token": FD_KEY}
    url = f"{FD_BASE}/{path.lstrip('/')}"
    resp = httpx.get(url, headers=headers, params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def self_test() -> None:
    """Verify the key is valid and WC 2026 competition is reachable."""
    data = get(f"competitions/{FD_COMP}")
    name = data.get("name", "?")
    season = (data.get("currentSeason") or {})
    start = season.get("startDate", "?")[:4]
    end = season.get("endDate", "?")[:4]
    print(f"football-data.org OK: {name} (season {start}–{end})")


if __name__ == "__main__":
    self_test()
