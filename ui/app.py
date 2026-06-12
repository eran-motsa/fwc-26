"""FastAPI app serving the always-on local UI.

Routes:
  GET  /                      -> redirect to today (or latest available day)
  GET  /day/{date}            -> daily view (placeholder for future, data when present)
  GET  /history               -> all days + my bet log + running points
  POST /bets                  -> record a chosen bet
  POST /bets/{id}/delete      -> remove a bet
  GET  /api/day/{date}        -> raw JSON snapshot (for debugging)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TZ_LOCAL, get_db  # noqa: E402
from model.report import compute_group_standings  # noqa: E402
from model.tournament import golden_boot, simulate_winner  # noqa: E402

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Mundial 2026 Betting Agent")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


def _fmt_date(iso: str) -> str:
    """yyyy-mm-dd → dd-mm-yyyy (display only; URLs stay ISO)."""
    if iso and len(iso) >= 10:
        y, m, d = iso[:10].split("-")
        return f"{d}-{m}-{y}"
    return iso or ""


def _weekday(iso: str) -> str:
    """yyyy-mm-dd → full weekday name."""
    if iso and len(iso) >= 10:
        from datetime import date as _date
        return _date.fromisoformat(iso[:10]).strftime("%A")
    return ""


_MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def _fmt_short(iso: str) -> str:
    """yyyy-mm-dd → '10 Jun' for compact nav labels."""
    if iso and len(iso) >= 10:
        _, m, d = iso[:10].split("-")
        return f"{int(d)} {_MONTHS[int(m)-1]}"
    return ""


templates.env.filters["fmtdate"] = _fmt_date
templates.env.filters["weekday"] = _weekday
templates.env.filters["fmtshort"] = _fmt_short


def _today() -> str:
    return datetime.now(ZoneInfo(TZ_LOCAL)).date().isoformat()


def _all_dates() -> list[str]:
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT date_local FROM fixtures ORDER BY date_local"
    ).fetchall()
    conn.close()
    return [r["date_local"] for r in rows]


def _snapshot(date_local: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT payload_json FROM daily_output WHERE date_local=?", (date_local,)
    ).fetchone()
    conn.close()
    return json.loads(row["payload_json"]) if row else None


def _fixtures_placeholder(date_local: str) -> list[dict]:
    """When no snapshot exists yet, show the matches as accessible placeholders."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, home_name, away_name, kickoff_local, round, venue, status, "
        "home_goals, away_goals FROM fixtures WHERE date_local=? ORDER BY kickoff_local",
        (date_local,),
    ).fetchall()
    conn.close()
    return [
        {"fixture_id": r["id"], "home": r["home_name"], "away": r["away_name"],
         "kickoff_local": r["kickoff_local"], "stage": r["round"],
         "venue": r["venue"], "status": r["status"],
         "home_goals": r["home_goals"], "away_goals": r["away_goals"],
         "model": None, "consensus": None, "value": None, "recommended_bet": None,
         "injuries": [], "lineups": [], "form_home": "—", "form_away": "—"}
        for r in rows
    ]


def _enrich_with_live_results(matches: list[dict], conn) -> list[dict]:
    """Overlay live DB status/goals onto snapshot data (snapshot may predate kickoff)."""
    if not matches:
        return matches
    ids = [m["fixture_id"] for m in matches]
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, status, home_goals, away_goals FROM fixtures WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    live = {r["id"]: r for r in rows}
    for m in matches:
        row = live.get(m["fixture_id"])
        if row:
            m["status"] = row["status"]
            m["home_goals"] = row["home_goals"]
            m["away_goals"] = row["away_goals"]
    return matches


def _bets_for(date_local: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM bets WHERE date_local=? ORDER BY created_at", (date_local,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/", response_class=HTMLResponse)
def index():
    dates = _all_dates()
    target = _today()
    if dates and target not in dates:
        # jump to nearest upcoming, else latest
        upcoming = [d for d in dates if d >= target]
        target = upcoming[0] if upcoming else dates[-1]
    return RedirectResponse(url=f"/day/{target}")


@app.get("/day/{date_local}", response_class=HTMLResponse)
def day_view(request: Request, date_local: str):
    dates = _all_dates()
    snap = _snapshot(date_local)
    conn = get_db()
    groups = compute_group_standings(conn)
    if snap:
        matches = _enrich_with_live_results(snap["matches"], conn)
        tournament = snap.get("tournament", {})
        generated_at = snap.get("generated_at")
    else:
        matches = _fixtures_placeholder(date_local)
        tournament = {}
        generated_at = None
    conn.close()
    idx = dates.index(date_local) if date_local in dates else -1
    prev_d = dates[idx - 1] if idx > 0 else None
    next_d = dates[idx + 1] if 0 <= idx < len(dates) - 1 else None
    return templates.TemplateResponse(request, "day.html", {
        "date_local": date_local, "matches": matches,
        "tournament": tournament, "groups": groups,
        "generated_at": generated_at,
        "prev_d": prev_d, "next_d": next_d, "today": _today(),
        "bets": _bets_for(date_local), "has_snapshot": snap is not None,
    })


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    conn = get_db()
    days = conn.execute(
        "SELECT date_local, generated_at FROM daily_output ORDER BY date_local DESC"
    ).fetchall()
    bets = conn.execute("SELECT * FROM bets ORDER BY date_local DESC, created_at DESC").fetchall()
    total_pts = conn.execute(
        "SELECT COALESCE(SUM(points_awarded),0) AS p FROM bets WHERE result!='pending'"
    ).fetchone()["p"]
    conn.close()
    return templates.TemplateResponse(request, "history.html", {
        "days": [dict(d) for d in days],
        "bets": [dict(b) for b in bets], "total_points": round(total_pts, 2),
    })


@app.post("/bets")
def add_bet(
    date_local: str = Form(...), fixture_id: int = Form(...),
    predicted_home: int = Form(...), predicted_away: int = Form(...),
    odds_taken: float = Form(0.0), stage_bonus: float = Form(0.0),
    notes: str = Form(""),
):
    conn = get_db()
    direction = ("home" if predicted_home > predicted_away
                 else "away" if predicted_away > predicted_home else "draw")
    conn.execute(
        """INSERT INTO bets(date_local, fixture_id, market, selection,
             predicted_home, predicted_away, odds_taken, stage_bonus, notes,
             result, created_at)
           VALUES(?,?,?,?,?,?,?,?,?, 'pending', ?)""",
        (date_local, fixture_id, "exact",
         f"{predicted_home}-{predicted_away} ({direction})",
         predicted_home, predicted_away, odds_taken, stage_bonus, notes,
         datetime.now(ZoneInfo(TZ_LOCAL)).isoformat()),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/day/{date_local}", status_code=303)


@app.post("/bets/{bet_id}/delete")
def delete_bet(bet_id: int, date_local: str = Form(...)):
    conn = get_db()
    conn.execute("DELETE FROM bets WHERE id=?", (bet_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url=f"/day/{date_local}", status_code=303)


@app.get("/api/day/{date_local}")
def api_day(date_local: str):
    return _snapshot(date_local) or {"date_local": date_local, "matches": _fixtures_placeholder(date_local)}


@app.get("/table", response_class=HTMLResponse)
def table_view(request: Request):
    conn = get_db()
    groups = compute_group_standings(conn)
    conn.close()
    return templates.TemplateResponse(request, "table.html", {
        "groups": groups, "today": _today(),
    })


@app.get("/trophy", response_class=HTMLResponse)
def trophy_view(request: Request):
    return templates.TemplateResponse(request, "trophy.html", {
        "winner": simulate_winner()[:12],
        "golden_boot": golden_boot(),
        "today": _today(),
    })


# Canonical stage order for display.
STAGE_ORDER = [
    "Group Stage", "Round of 32", "Round of 16",
    "Quarter-finals", "Semi-finals", "3rd Place Final", "Final",
]


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request, saved: int = 0):
    conn = get_db()
    rows = {r["stage"]: r for r in conn.execute(
        "SELECT stage, exact_bonus, odds_multiplier FROM scoring_rules").fetchall()}
    conn.close()
    ordered = [dict(rows[s]) for s in STAGE_ORDER if s in rows]
    # include any custom stages not in the canonical order
    ordered += [dict(r) for s, r in rows.items() if s not in STAGE_ORDER]
    return templates.TemplateResponse(request, "settings.html", {
        "rules": ordered, "saved": bool(saved),
    })


@app.post("/settings")
async def save_settings(request: Request):
    """Persist edited exact_bonus + odds_multiplier for every stage."""
    form = await request.form()
    conn = get_db()
    stages = {k.split("__", 1)[1] for k in form.keys() if k.startswith("bonus__")}
    for stage in stages:
        try:
            bonus = float(form.get(f"bonus__{stage}", 0) or 0)
            mult = float(form.get(f"mult__{stage}", 1) or 1)
        except ValueError:
            continue
        conn.execute(
            "UPDATE scoring_rules SET exact_bonus=?, odds_multiplier=? WHERE stage=?",
            (bonus, mult, stage),
        )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/settings?saved=1", status_code=303)

