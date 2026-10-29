# FILE: server/directory.py
"""
The sector directory: every company the app can put on a watchlist by sector.

Two sources, merged by NSE symbol:

  * the companies the app already knows (coverage, training lists,
    watchlists - live.universe()), with their sector and size;
  * NSE's published index lists (Nifty Total Market, Nifty 500, Microcap
    250 - about 1,000 companies with their industry), downloaded on demand
    and cached in data/live/directory.json for a week.

NSE names a few industries differently from the training lists; ALIASES maps
them onto the app's sector names so one sector is one entry, not two.
"""

import json
import re
import threading
import time

from server import data as D
from server import live

CACHE = live.LIVE / "directory.json"
MAX_AGE = 7 * 86400
ALIASES = {
    "automobile and auto components": "Automobiles and Auto Components",
    "healthcare": "Healthcare and Medical Devices",
    "metals & mining": "Metals and Mining",
    "power": "Power and Renewable Energy",
}
_lock = threading.Lock()


def _key(s):
    return re.sub(r"[^a-z]", "", (s or "").lower().replace("&", "and"))


def _canon(industry, known):
    """An NSE industry name -> the app's sector name for it."""
    if not industry:
        return ""
    alias = ALIASES.get(industry.strip().lower())
    if alias:
        return alias
    return known.get(_key(industry), industry.strip())


def _read_cache():
    try:
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("rows"), list) else None
    except (OSError, ValueError):
        return None


def refresh():
    """Download NSE's index lists into the cache. -> number of companies, or raises when NSE gave nothing."""
    import nse_source

    rows = nse_source.index_constituents()
    if not rows:
        raise RuntimeError("NSE did not answer (it blocks some networks and VPNs); the directory keeps the companies the app already knows")
    with _lock:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"fetched": time.time(), "rows": rows}), encoding="utf-8")
    return len(rows)


def companies():
    """-> {ticker: {ticker, name, sector, cap, lists, source}} - known companies first, NSE's lists after."""
    known = live.universe()
    sectors = {_key(e["sector"]): e["sector"] for e in known.values() if e["sector"]}
    out = {t: {**e, "source": "app"} for t, e in known.items()}
    by_symbol = {t.split(".")[0].upper(): t for t in out}
    cache = _read_cache()
    for r in (cache or {}).get("rows", []):
        sym = r.get("symbol", "").upper()
        if not sym or not live.TICKER.match(sym):
            continue
        sector = _canon(r.get("industry"), sectors)
        hit = by_symbol.get(sym)
        if hit:
            if not out[hit]["sector"] and sector:
                out[hit]["sector"] = sector
            continue
        t = f"{sym}.NS"
        out[t] = {"ticker": t, "name": r.get("name") or sym, "sector": sector, "cap": "", "lists": [], "source": "nse"}
    return out


def state():
    cache = _read_cache()
    return {"nse_fetched": cache.get("fetched") if cache else None, "nse_companies": len(cache["rows"]) if cache else 0,
            "stale": not cache or time.time() - cache.get("fetched", 0) > MAX_AGE}


def sectors():
    """-> [{sector, count, known}] where known = companies the app already has data for."""
    counts = {}
    for e in companies().values():
        s = e["sector"] or "Unclassified"
        c = counts.setdefault(s, {"sector": s, "count": 0, "known": 0})
        c["count"] += 1
        c["known"] += e["source"] == "app"
    return {**state(), "sectors": sorted(counts.values(), key=lambda c: (-c["count"], c["sector"]))}


def in_sectors(names):
    want = {n for n in names if n}
    rows = [e for e in companies().values() if (e["sector"] or "Unclassified") in want]
    return D.clean(sorted(rows, key=lambda e: (e["sector"], e["name"])))


def everyone():
    return D.clean(sorted(companies().values(), key=lambda e: e["name"]))
