#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Mundial 2026 Agent — one-command setup for macOS (Apple Silicon).
# Installs everything locally and leaves you with an always-on UI at :8000.
#
# Usage:
#   1) cp .env.example .env   and paste your two free API keys
#   2) bash scripts/setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT"
echo "▶ Project: $PROJECT"

# 1. Homebrew (for uv) ────────────────────────────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
  echo "▶ Installing Homebrew…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

# 2. uv (Python manager) ──────────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
  echo "▶ Installing uv…"
  brew install uv
fi
UV="$(command -v uv)"
echo "▶ uv at: $UV"

# 3. Python 3.14 + virtualenv + deps ──────────────────────────────────────────
echo "▶ Installing Python 3.14 and dependencies…"
uv python install 3.14
uv sync || uv pip install -e . --python 3.14
# numpy/scipy/fastapi/etc. come from pyproject.toml — installed locally in .venv

# 4. .env check ───────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  echo "✗ .env not found. Run: cp .env.example .env  and paste your API keys."
  exit 1
fi

# 5. Initialise database ──────────────────────────────────────────────────────
echo "▶ Initialising database…"
uv run python -m db.init_db

# 6. Verify API connectivity (first real call — no empty data) ────────────────
echo "▶ Testing API connectivity…"
uv run python -m ingestion.client
uv run python -m ingestion.odds_client

# 7. Backfill: fixtures + history + first snapshot ───────────────────────────
echo "▶ Backfilling fixtures, ratings and first snapshots…"
uv run python -m scripts.backfill

# 8. Install launchd jobs (11:00 results, 16:00 ingest, 16:30 report, UI) ─────
echo "▶ Installing launchd jobs…"
LA="$HOME/Library/LaunchAgents"
mkdir -p "$LA"
for f in results ingest report ui; do
  src="scripts/com.eran.mundial.$f.plist"
  dst="$LA/com.eran.mundial.$f.plist"
  sed -e "s#__PROJECT__#$PROJECT#g" -e "s#__UV__#$UV#g" "$src" > "$dst"
  launchctl unload "$dst" 2>/dev/null || true
  launchctl load "$dst"
  echo "  loaded com.eran.mundial.$f"
done

echo ""
echo "✅ Done. The UI is running (always-on) at:  http://127.0.0.1:8000"
echo "   • 11:00 settles yesterday's results"
echo "   • 16:00 pulls today's data, 16:30 builds the day's recommendations"
echo "   Logs are in $PROJECT/data/*.log"
