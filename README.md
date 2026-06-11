# FIFA World Cup 2026 Betting Agent

A fully local agent for the FIFA World Cup 2026 betting pool with friends. It ingests
fixtures, injuries, lineups and bookmaker odds daily, runs a Dixon-Coles statistical model,
and recommends the exact-score bet that **maximises points under your league's custom
scoring system** — all surfaced in an always-on local web UI.

## What it does

- **16:00 (Israel)** — pulls the day's fixtures, injuries, lineups, and bookmaker odds.
- **16:30** — refits team ratings, predicts every match, computes the bookmaker consensus
  and value edge, and saves the day's snapshot (the UI view + permanent history).
- **11:00** — pulls yesterday's final scores and settles your bets, awarding points by the
  league rules.
- **Always-on UI** at `http://127.0.0.1:8000` — daily view with each match's model
  probabilities, bookmaker consensus, value edge, and the recommended exact-score bet.
  Add your chosen bets; browse full history and your running points total. Future days are
  accessible placeholders that fill in on their day.

## Scoring rules (your league)

- Correct **direction** (1/X/2) earns that direction's odds value × stage multiplier.
- Correct **exact score** additionally earns the stage's bonus (Group +2, R32/R16 +4, QF +6,
  SF +8, Final +10 — editable in the `scoring_rules` table).
- Wrong direction earns 0.

The recommendation engine uses the model's full scoreline distribution to pick the bet with
the highest expected points: `EP = P(direction)·odds·mult + P(exact)·bonus`.

## Setup (one command)

1. Get three free API keys:
   - **api-football.com** (direct, not RapidAPI) — fixtures, lineups, H2H history
   - **the-odds-api.com** — bookmaker match odds and outright winner/golden boot odds
   - **football-data.org** — fixture schedule and live results (free tier, WC coverage)
2. Configure and run:
   ```bash
   cp .env.example .env      # paste both keys
   bash scripts/setup.sh     # installs uv, Python 3.14, deps, DB, jobs, UI
   ```
3. Open `http://127.0.0.1:8000`.

`setup.sh` installs everything locally (uv, Python 3.14, numpy/scipy/FastAPI, SQLite via the
stdlib), verifies API connectivity with a real first call, backfills fixtures + ratings +
snapshots, and installs four launchd jobs (results, ingest, report, always-on UI).

## Manual commands (optional)

```bash
uv run python -m ingestion.client      # API connectivity self-test
uv run python -m ingestion.run_daily   # the 16:00 job
uv run python -m model.run_report      # the 16:30 job
uv run python -m model.run_results     # the 11:00 settlement job
uv run uvicorn ui.app:app --port 8000  # run the UI manually
```

## Notes

- Free tiers are respected: API-Football calls are counted against the 100/day limit; odds
  pulls are batched to stay within The Odds API's monthly credits.
- Before the tournament starts (11 Jun), in-tournament data is empty, so ratings are seeded
  from each team's recent qualifiers/friendlies.
- The odds feed is read-only — used for statistics and value comparison, not for placing bets.
- The €/₪ stake isn't tracked by the app; standings are by points, top 3 win the pot.
