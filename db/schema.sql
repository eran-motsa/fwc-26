-- Mundial 2026 Betting Agent — SQLite schema
-- Run once via scripts/init_db.py (which executes this file).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS teams (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  code          TEXT,
  group_letter  TEXT
);

CREATE TABLE IF NOT EXISTS fixtures (
  id              INTEGER PRIMARY KEY,     -- football-data.org fixture id
  date_utc        TEXT NOT NULL,
  date_local      TEXT NOT NULL,           -- YYYY-MM-DD in Asia/Jerusalem
  kickoff_local   TEXT,                    -- HH:MM in Asia/Jerusalem
  stage           TEXT,                    -- 'Group Stage','Round of 32',...
  round           TEXT,
  home_id         INTEGER,
  away_id         INTEGER,
  home_name       TEXT,
  away_name       TEXT,
  venue           TEXT,
  status          TEXT,                    -- 'NS','FT','LIVE',...
  home_goals      INTEGER,
  away_goals      INTEGER,
  apif_fixture_id INTEGER                  -- API-Football id, set on match day for lineup pulls
);

-- Historical matches (qualifiers + friendlies) used to seed model ratings.
CREATE TABLE IF NOT EXISTS team_matches (
  fixture_id    INTEGER,
  team_id       INTEGER,
  opp_id        INTEGER,
  goals_for     INTEGER,
  goals_against INTEGER,
  date_utc      TEXT,
  is_home       INTEGER
);

CREATE TABLE IF NOT EXISTS injuries (
  fixture_id INTEGER, team_id INTEGER, player TEXT, reason TEXT, pulled_at TEXT
);

CREATE TABLE IF NOT EXISTS lineups (
  fixture_id INTEGER, team_id INTEGER, player TEXT, pos TEXT,
  is_starter INTEGER, pulled_at TEXT
);

-- Model attack/defence ratings, recomputed daily.
CREATE TABLE IF NOT EXISTS ratings (
  team_id INTEGER PRIMARY KEY, attack REAL, defence REAL, computed_at TEXT
);

-- Per-match model output (full scoreline distribution stored as JSON).
CREATE TABLE IF NOT EXISTS predictions (
  fixture_id     INTEGER PRIMARY KEY,
  p_home REAL, p_draw REAL, p_away REAL,
  exp_home_goals REAL, exp_away_goals REAL,
  top_scoreline  TEXT, over25 REAL, btts REAL,
  score_matrix_json TEXT,                   -- 2D array of P(i-j)
  computed_at    TEXT
);

-- Raw bookmaker odds per fixture.
CREATE TABLE IF NOT EXISTS odds (
  fixture_id INTEGER, bookmaker TEXT, market TEXT,
  o_home REAL, o_draw REAL, o_away REAL, o_over25 REAL, o_under25 REAL,
  pulled_at TEXT
);

-- Margin-removed, averaged consensus per fixture (also used as scoring odds).
CREATE TABLE IF NOT EXISTS odds_consensus (
  fixture_id INTEGER PRIMARY KEY,
  cp_home REAL, cp_draw REAL, cp_away REAL, cp_over25 REAL,
  -- Fair decimal odds derived from consensus (1 / probability) — used by the
  -- scoring engine as the "מכפיל יחסים" direction value.
  fair_home REAL, fair_draw REAL, fair_away REAL,
  n_books INTEGER, computed_at TEXT
);

-- Tournament outright markets (winner, golden boot).
CREATE TABLE IF NOT EXISTS outrights (
  market TEXT, selection TEXT, decimal_odds REAL, implied REAL, pulled_at TEXT
);

-- Pre-tournament golden boot contenders seeded from WC 2022 top scorers.
CREATE TABLE IF NOT EXISTS golden_boot_candidates (
  player    TEXT PRIMARY KEY,
  team_id   INTEGER,
  team_name TEXT,
  goals     INTEGER DEFAULT 0,
  rank      INTEGER,
  source    TEXT,
  created_at TEXT
);

-- Stage scoring config (the custom league rules from the screenshot).
CREATE TABLE IF NOT EXISTS scoring_rules (
  stage         TEXT PRIMARY KEY,
  exact_bonus   REAL NOT NULL,    -- 'בול' bonus added on exact-score hit
  odds_multiplier REAL NOT NULL   -- 'מכפיל יחסים' multiplier on the direction odds
);

-- One full snapshot per day (what the UI renders + becomes history).
CREATE TABLE IF NOT EXISTS daily_output (
  date_local   TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  generated_at TEXT
);

-- My chosen bets + their results.
CREATE TABLE IF NOT EXISTS bets (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  date_local  TEXT,
  fixture_id  INTEGER,
  market      TEXT,        -- 'exact' (the core game), 'outright_winner', 'golden_boot'
  selection   TEXT,        -- e.g. '2-1' (home-away) / 'Brazil' / player name
  predicted_home INTEGER,  -- for exact-score bets
  predicted_away INTEGER,
  odds_taken  REAL,        -- direction odds at time of bet
  stage_bonus REAL,        -- bonus that would apply on exact hit
  notes       TEXT,
  result      TEXT DEFAULT 'pending',   -- 'pending','won_exact','won_direction','lost'
  points_awarded REAL,     -- filled by the 11:00 results job
  created_at  TEXT
);

-- Tracks API call counts per day to respect free-tier limits.
CREATE TABLE IF NOT EXISTS api_meta (key TEXT PRIMARY KEY, value TEXT);

-- Cached head-to-head results per team pair (keyed by sorted APIF team IDs).
CREATE TABLE IF NOT EXISTS h2h_cache (
  team1_apif INTEGER,
  team2_apif INTEGER,
  payload_json TEXT,
  fetched_at TEXT,
  PRIMARY KEY (team1_apif, team2_apif)
);
