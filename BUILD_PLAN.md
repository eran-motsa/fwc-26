# Mundial 2026 Betting Agent — Architecture (as built)

A fully local agent for the FIFA World Cup 2026 betting pool. It ingests data daily, runs a
Dixon-Coles model, recommends the exact-score bet that maximises points under a custom
league scoring system, and serves an always-on local web UI. This document describes what
was actually built; `README.md` is the quickstart.

**Hardware target:** MacBook Pro M4 Max, 24 GB RAM, latest macOS
**Python:** 3.14.5 (managed by uv)
**Runtime:** Local. Always-on UI; all insight surfaced in the UI (no Cursor/MCP dependency).
**Tournament:** 11 Jun – 19 Jul 2026, 48 teams, 104 matches
**Timezone:** Asia/Jerusalem. Jobs at 11:00 (results), 16:00 (ingest), 16:30 (model+report).

---

## 0. Expectations

No model predicts exact scores reliably. The engine outputs probabilities and the bet with
the highest **expected league points** given your scoring rules. Coverage of in-tournament
data is empty until kickoff, so ratings are seeded from recent qualifiers/friendlies. The
odds feed is read-only — statistics and value comparison only, not placing bets.

---

## 1. Repo layout (actual)

```
mundial-agent/
├── README.md                  # quickstart
├── BUILD_PLAN.md              # this document
├── pyproject.toml             # uv, requires-python >=3.14
├── .env.example               # API keys + config
├── .gitignore
├── config.py                  # shared config, DB connection, key checks
├── Dockerfile                 # optional UI container
├── docker-compose.yml         # optional (UI only)
├── db/
│   ├── schema.sql             # all tables
│   └── init_db.py             # creates schema + seeds scoring_rules
├── ingestion/
│   ├── client.py              # API-Football client + daily call counter + self_test
│   ├── odds_client.py         # The Odds API client + self_test
│   ├── fixtures.py            # schedule + results, UTC→local conversion
│   ├── teams.py               # recent qualifier/friendly matches (ratings seed)
│   ├── injuries.py            # injuries + lineups for a day's fixtures
│   ├── odds.py                # per-book odds + margin-removed consensus + outrights
│   └── run_daily.py           # 16:00 orchestrator
├── model/
│   ├── dixon_coles.py         # bounded MLE fit, score matrix, market derivation
│   ├── ratings.py             # fit + persist attack/defence + home_adv + rho
│   ├── scoring.py             # custom league rules: optimal_bet + score_bet
│   ├── predict.py             # per-fixture prediction + stored score matrix
│   ├── tournament.py          # winner probabilities + golden-boot placeholder
│   ├── report.py              # builds + saves the daily snapshot
│   ├── run_report.py          # 16:30 orchestrator
│   └── run_results.py         # 11:00 results + bet settlement
├── ui/
│   ├── app.py                 # FastAPI: day view, history, settings, bet CRUD
│   ├── templates/
│   │   ├── base.html          # branding header + nav (original trophy emblem)
│   │   ├── day.html           # daily match cards + recommended bet + add-bet
│   │   ├── history.html       # snapshots + bet log + running points
│   │   └── settings.html      # editable per-stage scoring rules
│   └── static/style.css       # FIFA 2026 black/gold "We Are 26" theme
├── scripts/
│   ├── setup.sh               # one-command bootstrap (install → DB → backfill → jobs)
│   ├── backfill.py            # fixtures + history + ratings + snapshots on first run
│   ├── com.eran.mundial.results.plist   # launchd 11:00
│   ├── com.eran.mundial.ingest.plist    # launchd 16:00
│   ├── com.eran.mundial.report.plist    # launchd 16:30
│   └── com.eran.mundial.ui.plist        # launchd always-on UI
└── data/                      # SQLite DB + job logs (gitignored)
```

---

## 2. Stack & setup

uv-managed Python 3.14 with httpx, numpy, scipy, fastapi, uvicorn, jinja2,
python-multipart, python-dotenv. SQLite via the stdlib (no server). One-command bootstrap:

```bash
cp .env.example .env      # paste both free keys
bash scripts/setup.sh
```

`setup.sh` installs Homebrew/uv if missing, installs Python 3.14 + deps, initialises the DB,
runs a real first API call to verify connectivity (no empty data), backfills, and loads the
four launchd jobs. Two free keys: api-football.com (100 calls/day) and the-odds-api.com
(500 credits/month).

---

## 3. Data sources

**API-Football v3** (`league=1`, `season=2026`): fixtures, injuries, lineups, team history.
The client counts calls against the 100/day limit and exposes `self_test()` (hits `/status`).

**The Odds API** (`soccer_fifa_world_cup`): per-match h2h + totals and tournament outrights
from global books (Pinnacle, Bet365, FanDuel, …). `ingestion/odds.py` stores per-book rows
and computes a **margin-removed consensus** (invert odds → normalise per book → average),
deriving fair decimal odds that feed both the value comparison and the scoring engine.

Pre-tournament, in-tournament coverage is empty, so `teams.py` pulls each side's recent
matches to seed ratings.

---

## 4. Model

**Dixon-Coles** bivariate-Poisson (`model/dixon_coles.py`):
- Bounded maximum-likelihood fit of per-team attack/defence + home advantage + rho.
  Bounds (`±2` on ratings, `rho∈[-0.2,0.2]`, `home_adv∈[0,1]`) keep the fit stable on the
  small samples available before/early in the tournament.
- `score_matrix(...)` builds a 9×9 P(home=i, away=j) grid with the low-score τ correction.
- `derive_markets(...)` reduces it to 1X2, expected goals, over 2.5, BTTS, top scoreline.

`predict.py` stores the full score matrix (JSON) per fixture so the scoring engine can use
exact-score probabilities. `tournament.py` blends model strength with the bookmaker outright
consensus for trophy probabilities; golden boot is a placeholder until squads/lineups publish.

---

## 5. Custom scoring engine (`model/scoring.py`)

The league rules, configurable per stage (see §7):

- **Correct direction (1/X/2):** earn `direction_odds × odds_multiplier`.
- **Exact score also correct:** additionally earn the stage's `exact_bonus`.
- **Wrong direction:** 0.

```
points = direction_odds × multiplier ( + exact_bonus if exact )
```

Worked example reproduced by the engine (odds 1.2/3.2/5.7):
- guess 1-0, actual 2-0 → direction right, exact wrong → 1.2
- guess 1-2, actual 1-2 → exact right → 5.7 + bonus

`optimal_bet(score_matrix, fair_home, fair_draw, fair_away, exact_bonus, mult)` evaluates
every scoreline's expected points `EP = P(direction)·odds·mult + P(exact)·bonus` and returns
the maximiser plus the top-5 table shown in the UI. `score_bet(...)` settles a finished bet.
A keyword matcher maps each fixture's round text to a stage rule.

---

## 6. Daily automation (launchd, Asia/Jerusalem)

- **11:00 — results/settlement** (`model/run_results.py`): refresh final scores, settle the
  previous day's pending bets via `score_bet`, write `points_awarded` + result label.
- **16:00 — ingestion** (`ingestion/run_daily.py`): fixtures, injuries, lineups for the day's
  teams, bookmaker odds + consensus, outrights. Chosen so the freshest lineup/injury/odds
  data lands before the earliest 19:00 local kickoff.
- **16:30 — model + report** (`model/run_report.py`): refit ratings, predict the day, build
  and save the day snapshot.
- **Always-on UI** (`com.eran.mundial.ui.plist`): `KeepAlive` uvicorn on `127.0.0.1:8000`.

launchd (not cron) — survives sleep/wake, logs to `data/*.log`.

---

## 7. UI (`ui/app.py` + templates)

Always-on FastAPI + Jinja2, FIFA 2026 black/gold "We Are 26" theme with an original
trophy-in-26 SVG emblem (an interpretation, not a copy of the official mark).

- **Daily view** (`/day/{date}`): tournament panel (winner probabilities, golden-boot
  contenders) + one card per match showing teams, kickoff (local), stage, venue, recent form,
  injuries, lineups, model 1X2/xG/top score/over-2.5/BTTS, bookmaker consensus + fair odds,
  the value edge (highlighted where model > market), and the **recommended exact-score bet**
  with its top-5 table. An add-bet form (prefilled with the recommendation) stores to SQLite.
  Future days render as accessible placeholders that fill in on their daily job.
- **History** (`/history`): every saved daily snapshot + the full bet log with results and a
  running points total (first 3 places win the pot; the stake isn't tracked by the app).
- **Settings** (`/settings`): editable per-stage **exact bonus** and **odds multiplier**.
  Saved values apply immediately to new recommendations and to settlement of pending bets,
  since both read the rules live from the DB.

---

## 8. Database (`db/schema.sql`)

teams, fixtures, team_matches, injuries, lineups, ratings, predictions (with stored score
matrix), odds, odds_consensus (incl. fair odds), outrights, scoring_rules (exact_bonus +
odds_multiplier per stage), daily_output (one JSON snapshot per day = the history source of
truth), bets (predictions, result, points_awarded), api_meta (daily call counter, fitted
home_adv/rho).

---

## 9. Docker (optional)

Native uv + launchd is the recommended path and runs faster. A Dockerfile + compose are
included to run only the UI in a container if desired; the scheduled jobs need host
scheduling (launchd), so they stay native.

---

## 10. Verification performed

Tested end-to-end in development: Dixon-Coles fit (probabilities sum to 1, sensible
scorelines after bounding), the scoring engine against the worked example (1.2 / exact+bonus
/ 0), full pipeline (ratings → predictions → recommended bet using the correct stage bonus →
tournament probabilities), the full bet lifecycle (add via form → settle → correct points),
all UI routes rendering (today/future/history/settings), and the settings page changing both
knobs and shifting recommendations/settlement accordingly.

---

## 11. Known limitations / next steps

- Golden-boot ranking is a placeholder until squad/lineup or top-scorer data is live.
- Stage keyword matching expects recognisable round names; could be made fully configurable.
- UI validated via FastAPI's TestClient (routing + rendering), not a live browser session.
