"""Shared configuration and SQLite helpers."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "").strip()
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
FD_KEY = os.getenv("FD_KEY", "").strip()
WC_LEAGUE_ID = int(os.getenv("WC_LEAGUE_ID", "1"))
WC_SEASON = int(os.getenv("WC_SEASON", "2026"))
TZ_LOCAL = os.getenv("TZ_LOCAL", "Asia/Jerusalem")
DB_PATH = ROOT / os.getenv("DB_PATH", "data/mundial.db")
ODDS_REGIONS = os.getenv("ODDS_REGIONS", "eu,uk")

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
FD_BASE = "https://api.football-data.org/v4"
FD_COMP = "WC"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_SPORT_KEY = "soccer_fifa_world_cup"


def get_db() -> sqlite3.Connection:
    """Open the SQLite database with row access by column name."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def require_keys() -> None:
    """Fail loudly if API keys are missing, so we never run on empty data."""
    missing = []
    if not API_FOOTBALL_KEY:
        missing.append("API_FOOTBALL_KEY")
    if not ODDS_API_KEY:
        missing.append("ODDS_API_KEY")
    if not FD_KEY:
        missing.append("FD_KEY")
    if missing:
        raise SystemExit(
            "Missing required API key(s): "
            + ", ".join(missing)
            + "\nCopy .env.example to .env and paste your free keys "
            "(api-football.com, the-odds-api.com, football-data.org)."
        )
