"""API-Football v3 HTTP client with daily call counting and a connectivity test."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import API_FOOTBALL_BASE, API_FOOTBALL_KEY, get_db  # noqa: E402

DAILY_LIMIT = 100  # free tier


def _count_call() -> int:
    """Increment today's call counter; return new count."""
    today = date.today().isoformat()
    conn = get_db()
    key = f"af_calls_{today}"
    row = conn.execute("SELECT value FROM api_meta WHERE key=?", (key,)).fetchone()
    n = int(row["value"]) + 1 if row else 1
    conn.execute(
        "INSERT INTO api_meta(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(n)),
    )
    conn.commit()
    conn.close()
    return n


def get(endpoint: str, params: dict | None = None) -> dict:
    """GET an API-Football endpoint. Raises on HTTP or API-level errors."""
    n = _count_call()
    if n > DAILY_LIMIT:
        raise RuntimeError(
            f"API-Football daily limit ({DAILY_LIMIT}) reached ({n} calls). "
            "Wait until tomorrow or upgrade the plan."
        )
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    url = f"{API_FOOTBALL_BASE}/{endpoint.lstrip('/')}"
    resp = httpx.get(url, headers=headers, params=params or {}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"API-Football error on {endpoint}: {data['errors']}")
    return data


def self_test() -> None:
    """First call: hit /status and confirm the key works and quota remains.

    This is the explicit 'make the first API call to ensure it works and to not
    have empty data' step. Run before any ingestion.
    """
    data = get("status")
    resp = data.get("response", {})
    acct = resp.get("account", {})
    sub = resp.get("subscription", {})
    reqs = resp.get("requests", {})
    print("API-Football connectivity OK")
    print(f"  account : {acct.get('firstname','?')} {acct.get('lastname','')}".rstrip())
    print(f"  plan    : {sub.get('plan','?')} (active={sub.get('active')})")
    print(f"  requests: {reqs.get('current','?')}/{reqs.get('limit_day','?')} today")
    if reqs.get("limit_day") and reqs.get("current", 0) >= reqs["limit_day"]:
        raise SystemExit("API-Football quota for today is already exhausted.")


if __name__ == "__main__":
    self_test()
