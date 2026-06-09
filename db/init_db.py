"""Initialise the SQLite database: create tables and seed scoring rules.

Idempotent — safe to run repeatedly.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ROOT, get_db  # noqa: E402

# Scoring rules from the league screenshot.
# stage : (exact_bonus 'בול', odds_multiplier 'מכפיל יחסים')
SCORING_RULES = {
    "Group Stage": (2.0, 1.0),
    "Round of 32": (4.0, 1.0),
    "Round of 16": (4.0, 1.0),
    "Quarter-finals": (6.0, 1.0),
    # Sensible escalation for later rounds (adjust any time in the DB/UI):
    "Semi-finals": (8.0, 1.0),
    "Final": (10.0, 1.0),
    "3rd Place Final": (8.0, 1.0),
}


def main() -> None:
    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    conn = get_db()
    conn.executescript(schema)
    # Migrate existing DB: add apif_fixture_id column if it doesn't exist yet.
    try:
        conn.execute("ALTER TABLE fixtures ADD COLUMN apif_fixture_id INTEGER")
        conn.commit()
    except Exception:
        pass  # column already exists
    # Migrate: create golden_boot_candidates table if it doesn't exist yet.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS golden_boot_candidates (
          player TEXT PRIMARY KEY, team_id INTEGER, team_name TEXT,
          goals INTEGER DEFAULT 0, rank INTEGER, source TEXT, created_at TEXT
        )
    """)
    # Migrate: add apif_id column to teams if not present.
    try:
        conn.execute("ALTER TABLE teams ADD COLUMN apif_id INTEGER")
    except Exception:
        pass
    # Migrate: create h2h_cache table if not present.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS h2h_cache (
          team1_apif INTEGER, team2_apif INTEGER,
          payload_json TEXT, fetched_at TEXT,
          PRIMARY KEY (team1_apif, team2_apif)
        )
    """)
    conn.commit()
    for stage, (bonus, mult) in SCORING_RULES.items():
        conn.execute(
            "INSERT INTO scoring_rules(stage, exact_bonus, odds_multiplier) "
            "VALUES(?,?,?) ON CONFLICT(stage) DO UPDATE SET "
            "exact_bonus=excluded.exact_bonus, odds_multiplier=excluded.odds_multiplier",
            (stage, bonus, mult),
        )
    conn.commit()
    conn.close()
    print(f"Database initialised: schema + {len(SCORING_RULES)} scoring rules.")


if __name__ == "__main__":
    main()
