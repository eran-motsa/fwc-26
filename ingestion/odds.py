"""Pull bookmaker odds, store per-book rows, and compute a margin-removed
consensus that doubles as the scoring 'יחסים' (direction odds)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_db  # noqa: E402
from ingestion.odds_client import get_odds, get_outrights  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Odds API team names → football-data.org names used in our DB
_ODDS_TO_FD: dict[str, str] = {
    "Czech Republic":       "Czechia",
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "USA":                  "United States",
    "DR Congo":             "Congo DR",
    "Cape Verde":           "Cape Verde Islands",
}


def _match_fixture(home: str, away: str, date_local: str | None) -> int | None:
    """Map an Odds-API event (team names) to our fixture id by name match."""
    home = _ODDS_TO_FD.get(home, home)
    away = _ODDS_TO_FD.get(away, away)
    conn = get_db()
    q = ("SELECT id FROM fixtures WHERE "
         "LOWER(home_name)=LOWER(?) AND LOWER(away_name)=LOWER(?)")
    args = [home, away]
    if date_local:
        q += " AND date_local=?"
        args.append(date_local)
    row = conn.execute(q, args).fetchone()
    conn.close()
    return row["id"] if row else None


def sync_match_odds(date_local: str | None = None) -> int:
    """Pull h2h + totals odds, store per-book, compute consensus per fixture."""
    events = get_odds(markets="h2h,totals")
    conn = get_db()
    pulled = _now()
    n = 0
    by_fixture: dict[int, list[dict]] = {}
    for ev in events:
        home, away = ev.get("home_team"), ev.get("away_team")
        fx_id = _match_fixture(home, away, date_local)
        if fx_id is None:
            continue
        for bk in ev.get("bookmakers", []):
            o = {"home": None, "draw": None, "away": None,
                 "over25": None, "under25": None}
            for mk in bk.get("markets", []):
                if mk["key"] == "h2h":
                    for oc in mk["outcomes"]:
                        if oc["name"] == home:
                            o["home"] = oc["price"]
                        elif oc["name"] == away:
                            o["away"] = oc["price"]
                        else:
                            o["draw"] = oc["price"]
                elif mk["key"] == "totals":
                    for oc in mk["outcomes"]:
                        if oc.get("point") == 2.5 and oc["name"] == "Over":
                            o["over25"] = oc["price"]
                        elif oc.get("point") == 2.5 and oc["name"] == "Under":
                            o["under25"] = oc["price"]
            conn.execute(
                "INSERT INTO odds(fixture_id, bookmaker, market, o_home, o_draw, "
                "o_away, o_over25, o_under25, pulled_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (fx_id, bk["key"], "h2h+totals", o["home"], o["draw"],
                 o["away"], o["over25"], o["under25"], pulled),
            )
            by_fixture.setdefault(fx_id, []).append(o)
            n += 1
    # consensus
    for fx_id, rows in by_fixture.items():
        _store_consensus(conn, fx_id, rows, pulled)
    conn.commit()
    conn.close()
    print(f"Stored {n} bookmaker odds rows; consensus for {len(by_fixture)} fixtures.")
    return n


def _store_consensus(conn, fx_id: int, rows: list[dict], pulled: str) -> None:
    """Average margin-removed implied probs across books; derive fair odds."""
    probs_h, probs_d, probs_a, probs_o = [], [], [], []
    for o in rows:
        if o["home"] and o["draw"] and o["away"]:
            inv = [1 / o["home"], 1 / o["draw"], 1 / o["away"]]
            s = sum(inv)
            probs_h.append(inv[0] / s)
            probs_d.append(inv[1] / s)
            probs_a.append(inv[2] / s)
        if o["over25"] and o["under25"]:
            inv = [1 / o["over25"], 1 / o["under25"]]
            s = sum(inv)
            probs_o.append(inv[0] / s)
    if not probs_h:
        return
    cp_h = sum(probs_h) / len(probs_h)
    cp_d = sum(probs_d) / len(probs_d)
    cp_a = sum(probs_a) / len(probs_a)
    cp_o = sum(probs_o) / len(probs_o) if probs_o else None
    conn.execute(
        """INSERT INTO odds_consensus(
             fixture_id, cp_home, cp_draw, cp_away, cp_over25,
             fair_home, fair_draw, fair_away, n_books, computed_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(fixture_id) DO UPDATE SET
             cp_home=excluded.cp_home, cp_draw=excluded.cp_draw,
             cp_away=excluded.cp_away, cp_over25=excluded.cp_over25,
             fair_home=excluded.fair_home, fair_draw=excluded.fair_draw,
             fair_away=excluded.fair_away, n_books=excluded.n_books,
             computed_at=excluded.computed_at""",
        (fx_id, cp_h, cp_d, cp_a, cp_o,
         round(1 / cp_h, 2), round(1 / cp_d, 2), round(1 / cp_a, 2),
         len(probs_h), pulled),
    )


def sync_outrights() -> int:
    """Pull tournament winner outrights and store implied probabilities."""
    events = get_outrights()
    conn = get_db()
    pulled = _now()
    n = 0
    for ev in events:
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk["key"] != "outrights":
                    continue
                for oc in mk["outcomes"]:
                    price = oc["price"]
                    conn.execute(
                        "INSERT INTO outrights(market, selection, decimal_odds, "
                        "implied, pulled_at) VALUES(?,?,?,?,?)",
                        ("winner", oc["name"], price, round(1 / price, 4), pulled),
                    )
                    n += 1
    conn.commit()
    conn.close()
    print(f"Stored {n} outright rows.")
    return n


if __name__ == "__main__":
    sync_match_odds()
    sync_outrights()
