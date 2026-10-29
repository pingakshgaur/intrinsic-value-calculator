# FILE: server/indices.py
"""
Market indices and size classes a watchlist can take whole: NIFTY 50,
NIFTY 500, Bank Nifty, Large / Mid / Small cap and so on.

    catalog()          -> every index, with its aliases and what is cached
    match(text)        -> the indices a search box text means ("nifty50", "large cap")
    members(key)       -> {key, label, source, fetched, note, companies: [...]}

Constituents come from NSE's published index lists (nsearchives - plain CSV,
no login) and are cached in data/live/indices/ for a week. Without a network:

  * NIFTY 50 and SENSEX fall back to a bundled snapshot (late 2025);
  * the size classes fall back to the companies the app already knows with
    that market-cap tag (training lists, coverage, watchlists);
  * anything else says plainly that NSE did not answer.

SEBI's size classes follow the NSE indices: large cap = the top 100 (NIFTY
100), mid cap = the next 150 (NIFTY Midcap 150), small cap = the next 250
(NIFTY Smallcap 250).
"""

import json
import re
import threading
import time

from server import directory
from server import live

CACHE = live.LIVE / "indices"
MAX_AGE = 7 * 86400
_lock = threading.Lock()

# key, label, group, NSE list file, size-class fallback, aliases (beyond the label itself)
INDICES = [
    ("nifty50", "NIFTY 50", "Broad market", "ind_nifty50list.csv", None, ["nifty", "nse50", "nifty fifty"]),
    ("niftynext50", "NIFTY Next 50", "Broad market", "ind_niftynext50list.csv", None, ["next50", "junior nifty", "niftyjunior"]),
    ("nifty100", "NIFTY 100", "Broad market", "ind_nifty100list.csv", "Large", []),
    ("nifty200", "NIFTY 200", "Broad market", "ind_nifty200list.csv", None, []),
    ("nifty500", "NIFTY 500", "Broad market", "ind_nifty500list.csv", None, ["nse500", "cnx500"]),
    ("niftytotalmarket", "NIFTY Total Market", "Broad market", "ind_niftytotalmarket_list.csv", None, ["total market", "all nse"]),
    ("sensex", "SENSEX", "Broad market", None, None, ["bse sensex", "bse30", "sensex30"]),
    ("largecap", "Large cap", "Size", "ind_nifty100list.csv", "Large", ["large caps", "largecaps", "bluechip", "blue chip"]),
    ("midcap", "Mid cap", "Size", "ind_niftymidcap150list.csv", "Mid", ["mid caps", "midcaps", "nifty midcap 150", "midcap150"]),
    ("smallcap", "Small cap", "Size", "ind_niftysmallcap250list.csv", "Small", ["small caps", "smallcaps", "nifty smallcap 250", "smallcap250"]),
    ("microcap", "Micro cap", "Size", "ind_niftymicrocap250_list.csv", None, ["micro caps", "microcaps", "nifty microcap 250", "microcap250"]),
    ("niftymidcap100", "NIFTY Midcap 100", "Size", "ind_niftymidcap100list.csv", None, ["midcap100"]),
    ("niftysmallcap100", "NIFTY Smallcap 100", "Size", "ind_niftysmallcap100list.csv", None, ["smallcap100"]),
    ("niftybank", "NIFTY Bank", "Sector index", "ind_niftybanklist.csv", None, ["bank nifty", "banknifty", "banks"]),
    ("niftyit", "NIFTY IT", "Sector index", "ind_niftyitlist.csv", None, ["it stocks", "tech"]),
    ("niftypharma", "NIFTY Pharma", "Sector index", "ind_niftypharmalist.csv", None, ["pharma"]),
    ("niftyauto", "NIFTY Auto", "Sector index", "ind_niftyautolist.csv", None, ["auto", "autos"]),
    ("niftyfmcg", "NIFTY FMCG", "Sector index", "ind_niftyfmcglist.csv", None, ["fmcg"]),
    ("niftymetal", "NIFTY Metal", "Sector index", "ind_niftymetallist.csv", None, ["metal", "metals"]),
    ("niftyenergy", "NIFTY Energy", "Sector index", "ind_niftyenergylist.csv", None, ["energy"]),
    ("niftyrealty", "NIFTY Realty", "Sector index", "ind_niftyrealtylist.csv", None, ["realty", "real estate"]),
    ("niftypsubank", "NIFTY PSU Bank", "Sector index", "ind_niftypsubanklist.csv", None, ["psu bank", "psu banks", "psubanks"]),
    ("niftyfinance", "NIFTY Financial Services", "Sector index", "ind_niftyfinancelist.csv", None, ["finnifty", "fin nifty", "financial services"]),
    ("niftydefence", "NIFTY India Defence", "Sector index", "ind_niftyindiadefence_list.csv", None, ["defence", "defense", "nifty defence"]),
]
BY_KEY = {i[0]: i for i in INDICES}

# bundled snapshots (late 2025) for when NSE cannot be reached: symbol, name, industry
SNAPSHOT = {
    "nifty50": [
        ("ADANIENT", "Adani Enterprises", "Metals & Mining"), ("ADANIPORTS", "Adani Ports and Special Economic Zone", "Services"),
        ("APOLLOHOSP", "Apollo Hospitals Enterprise", "Healthcare"), ("ASIANPAINT", "Asian Paints", "Consumer Durables"),
        ("AXISBANK", "Axis Bank", "Financial Services"), ("BAJAJ-AUTO", "Bajaj Auto", "Automobile and Auto Components"),
        ("BAJFINANCE", "Bajaj Finance", "Financial Services"), ("BAJAJFINSV", "Bajaj Finserv", "Financial Services"),
        ("BEL", "Bharat Electronics", "Capital Goods"), ("BHARTIARTL", "Bharti Airtel", "Telecommunication"),
        ("CIPLA", "Cipla", "Healthcare"), ("COALINDIA", "Coal India", "Oil Gas & Consumable Fuels"),
        ("DRREDDY", "Dr. Reddy's Laboratories", "Healthcare"), ("EICHERMOT", "Eicher Motors", "Automobile and Auto Components"),
        ("ETERNAL", "Eternal", "Consumer Services"), ("GRASIM", "Grasim Industries", "Construction Materials"),
        ("HCLTECH", "HCL Technologies", "Information Technology"), ("HDFCBANK", "HDFC Bank", "Financial Services"),
        ("HDFCLIFE", "HDFC Life Insurance Company", "Financial Services"), ("HINDALCO", "Hindalco Industries", "Metals & Mining"),
        ("HINDUNILVR", "Hindustan Unilever", "Fast Moving Consumer Goods"), ("ICICIBANK", "ICICI Bank", "Financial Services"),
        ("INDIGO", "InterGlobe Aviation", "Services"), ("INFY", "Infosys", "Information Technology"),
        ("ITC", "ITC", "Fast Moving Consumer Goods"), ("JIOFIN", "Jio Financial Services", "Financial Services"),
        ("JSWSTEEL", "JSW Steel", "Metals & Mining"), ("KOTAKBANK", "Kotak Mahindra Bank", "Financial Services"),
        ("LT", "Larsen & Toubro", "Construction"), ("M&M", "Mahindra & Mahindra", "Automobile and Auto Components"),
        ("MARUTI", "Maruti Suzuki India", "Automobile and Auto Components"), ("MAXHEALTH", "Max Healthcare Institute", "Healthcare"),
        ("NESTLEIND", "Nestle India", "Fast Moving Consumer Goods"), ("NTPC", "NTPC", "Power"),
        ("ONGC", "Oil & Natural Gas Corporation", "Oil Gas & Consumable Fuels"), ("POWERGRID", "Power Grid Corporation of India", "Power"),
        ("RELIANCE", "Reliance Industries", "Oil Gas & Consumable Fuels"), ("SBILIFE", "SBI Life Insurance Company", "Financial Services"),
        ("SBIN", "State Bank of India", "Financial Services"), ("SHRIRAMFIN", "Shriram Finance", "Financial Services"),
        ("SUNPHARMA", "Sun Pharmaceutical Industries", "Healthcare"), ("TATACONSUM", "Tata Consumer Products", "Fast Moving Consumer Goods"),
        ("TMPV", "Tata Motors Passenger Vehicles", "Automobile and Auto Components"), ("TATASTEEL", "Tata Steel", "Metals & Mining"),
        ("TCS", "Tata Consultancy Services", "Information Technology"), ("TECHM", "Tech Mahindra", "Information Technology"),
        ("TITAN", "Titan Company", "Consumer Durables"), ("TRENT", "Trent", "Consumer Services"),
        ("ULTRACEMCO", "UltraTech Cement", "Construction Materials"), ("WIPRO", "Wipro", "Information Technology"),
    ],
}
SNAPSHOT["sensex"] = [r for r in SNAPSHOT["nifty50"] if r[0] in {
    "ADANIPORTS", "ASIANPAINT", "AXISBANK", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "ETERNAL", "HCLTECH", "HDFCBANK",
    "HINDUNILVR", "ICICIBANK", "INFY", "ITC", "KOTAKBANK", "LT", "M&M", "MARUTI", "NTPC", "POWERGRID", "RELIANCE", "SBIN",
    "SUNPHARMA", "TATASTEEL", "TCS", "TECHM", "TITAN", "TMPV", "TRENT", "ULTRACEMCO"}]


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("&", "and"))


def _names(i):
    return {_norm(i[1]), _norm(i[0]), *(_norm(a) for a in i[5])}


def _cache_file(key):
    return CACHE / f"{key}.json"


def _cached(key):
    try:
        d = json.loads(_cache_file(key).read_text(encoding="utf-8"))
        return d if isinstance(d.get("rows"), list) and d["rows"] else None
    except (OSError, ValueError, AttributeError):
        return None


def catalog():
    out = []
    for key, label, group, file, cap, aliases in INDICES:
        c = _cached(key)
        out.append({"key": key, "label": label, "group": group, "aliases": aliases, "count": len(c["rows"]) if c else None,
                    "fetched": c.get("fetched") if c else None, "online": bool(file)})
    return out


def match(text, limit=4):
    """The indices a search text names: exact or alias matches first, then prefixes (at least 3 letters)."""
    t = _norm(text)
    if len(t) < 3:
        return []
    exact = [i for i in INDICES if t in _names(i)]
    loose = [i for i in INDICES if i not in exact and any(n.startswith(t) for n in _names(i))] if len(t) >= 4 else []
    return [{"key": i[0], "label": i[1], "group": i[2]} for i in (exact + loose)[:limit]]


def _download(key):
    import nse_source

    file = BY_KEY[key][3]
    rows = nse_source.index_list(file) if file else []
    if rows:
        with _lock:
            CACHE.mkdir(parents=True, exist_ok=True)
            _cache_file(key).write_text(json.dumps({"fetched": time.time(), "rows": rows}), encoding="utf-8")
    return rows


def members(key, refresh=False):
    if key not in BY_KEY:
        raise KeyError(f"no index {key}")
    _, label, _, file, cap, _ = BY_KEY[key]
    c = _cached(key)
    rows, source, fetched, note = None, None, None, None
    if c and not refresh and time.time() - c.get("fetched", 0) < MAX_AGE:
        rows, source, fetched = c["rows"], "nse", c["fetched"]
    else:
        got = _download(key)
        if got:
            rows, source, fetched = got, "nse", time.time()
        elif c:
            rows, source, fetched = c["rows"], "nse", c["fetched"]
            note = "NSE did not answer just now; this is the list from the last download."
    known = directory.companies()
    by_symbol = {t.split(".")[0].upper(): e for t, e in known.items()}
    sectors = {directory._key(e["sector"]): e["sector"] for e in known.values() if e["sector"]}

    def entry(sym, name, industry):
        e = by_symbol.get(sym.upper())
        if e:
            return {"ticker": e["ticker"], "name": e["name"], "sector": e["sector"] or directory._canon(industry, sectors), "cap": e.get("cap") or (cap or "")}
        return {"ticker": f"{sym.upper()}.NS", "name": name or sym, "sector": directory._canon(industry, sectors) or "Unclassified", "cap": cap or ""}

    if rows is None and key in SNAPSHOT:
        rows, source = [{"symbol": s, "name": n, "industry": ind} for s, n, ind in SNAPSHOT[key]], "snapshot"
        note = ("NSE could not be reached, so this is the list bundled with the app (late 2025)." if file else
                "SENSEX is published by BSE; this is the list bundled with the app (late 2025).")
    if rows is None and cap:
        companies = [{"ticker": e["ticker"], "name": e["name"], "sector": e["sector"] or "Unclassified", "cap": cap}
                     for e in known.values() if (e.get("cap") or "").lower().startswith(cap.lower())]
        companies.sort(key=lambda e: e["name"])
        return {"key": key, "label": label, "source": "known", "fetched": None, "companies": companies,
                "note": f"NSE could not be reached, so these are the {len(companies)} companies the app already knows as {cap.lower()} cap. "
                        "Try again online for the full index."}
    if rows is None:
        return {"key": key, "label": label, "source": None, "fetched": None, "companies": [],
                "note": "NSE could not be reached (it blocks some networks and VPNs). Try again in a minute."}
    seen, companies = set(), []
    for r in rows:
        e = entry(r["symbol"], r.get("name"), r.get("industry"))
        if e["ticker"] not in seen and live.TICKER.match(e["ticker"]):
            seen.add(e["ticker"])
            companies.append(e)
    return {"key": key, "label": label, "source": source, "fetched": fetched, "companies": companies, "note": note}
