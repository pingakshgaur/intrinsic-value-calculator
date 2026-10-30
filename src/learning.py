# FILE: src/learning.py
"""
Learning data: every company the app knows about - the training list, the
auto-trainer's picks, every watchlist and every company the research agents
have judged - is one learning pool. The valuation report values the whole pool
alongside its own companies, and every agent run values its companies against
it, so the peer medians, the sector betas, the machine-learning models, the
Ensemble's weights, the HYBRID MODEL's calibration and the accuracy figures all
learn from every company, not only from the few being looked at.

What this adds is companies, not ticks. The models learn from one row per
company per financial year (that year's accounts -> the next year's price
change), so a live price on its own is not a training example, while another
company's twenty years of accounts are twenty. Live prices are used for what
they are good for: valuing each company at today's price (server/live.py).

    python run.py --learn            fetch and cache every learning company
    python run.py --train-universe data/live/learning_universe.csv
                                     train on them (the web app adds this flag
                                     to every valuation run while learning is on)
"""

import csv
import json
import time

import config

LIVE = config.DATA_DIR / "live"
UNIVERSE_CSV = LIVE / "learning_universe.csv"
WATCHLIST = LIVE / "watchlist.json"      # before watchlist libraries
WATCHLISTS = LIVE / "watchlists.json"
LISTS = (
    ("training list", config.DATA_DIR / "training_universe.csv"),
    ("auto-train", config.DATA_DIR / "auto_training_universe.csv"),
)
HEADER = ["company name", "sector name", "market cap", "ticker"]


def _read(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _watchlist():
    """Every company on any watchlist (the web app's libraries, or the old single list)."""
    try:
        b = json.loads(WATCHLISTS.read_text(encoding="utf-8"))
        return [{"ticker": t, **v} for t, v in (b.get("items") or {}).items()]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        return json.loads(WATCHLIST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def researched():
    """Every real company the research agents have ever judged, with its
    sector, latest first. Offline test runs (mock tickers without an exchange
    suffix) are left out. -> [{"name", "sector", "ticker"}]"""
    import sqlite3

    try:
        from agents import settings as S

        path = S.state_dir() / "blackboard.sqlite"
    except Exception:
        return []
    if not path.exists():
        return []
    try:
        con = sqlite3.connect(path, timeout=10)
        try:
            rows = con.execute(
                "SELECT company, ticker, json_extract(payload, '$.sector'), MAX(run_id) FROM verdicts "
                "WHERE company IS NOT NULL AND company != '' GROUP BY company ORDER BY MAX(run_id) DESC").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [{"name": c, "ticker": (t or "").strip(), "sector": s or ""} for c, t, s, _ in rows
            if "." in (t or "")]


def companies(exclude=None):
    """The learning pool - every company the app knows: the report list
    (data/companies.csv), the training lists, every watchlist and every company
    the agents have researched - de-duplicated by ticker, minus `exclude` (the
    rows a run values directly, so they are not in its frame twice).
    -> [{"name", "sector", "cap", "ticker", "lists"}]"""
    valued = exclude or ()
    bare = lambda t: (t or "").strip().upper().split(".")[0]  # noqa: E731  HAL.NS and HAL are one company
    skip_t = {bare(r.get("ticker")) for r in valued} - {""}
    skip_n = {(r.get("company name") or r.get("name") or "").strip() for r in valued} - {""}
    out = {}

    def add(tag, name, sector, cap, ticker):
        name, ticker = (name or "").strip(), (ticker or "").strip()
        if not ticker or bare(ticker) in skip_t or name in skip_n:
            return
        e = out.setdefault(ticker, {"name": name or ticker, "sector": (sector or "").strip() or "Unclassified",
                                    "cap": (cap or "").strip(), "ticker": ticker, "lists": []})
        if e["sector"] == "Unclassified" and (sector or "").strip():
            e["sector"] = sector.strip()   # a later list may know the sector a watchlist did not
        if tag not in e["lists"]:
            e["lists"].append(tag)

    lists = (("coverage", config.DEFAULT_INPUT),) + LISTS
    for tag, path in lists:
        for r in _read(path):
            add(tag, r.get("company name"), r.get("sector name"), r.get("market cap"), r.get("ticker"))
    for w in _watchlist():
        add("watchlist", w.get("name"), w.get("sector"), w.get("cap"), w.get("ticker"))
    for r in researched():
        add("researched", r["name"], r["sector"], "", r["ticker"])
    return list(out.values())


def write_csv(rows=None):
    """The learning companies as a run.py input file. -> path"""
    rows = companies() if rows is None else rows
    LIVE.mkdir(parents=True, exist_ok=True)
    with open(UNIVERSE_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for r in rows:
            w.writerow([r["name"], r["sector"], r["cap"], r["ticker"]])
    return UNIVERSE_CSV


def cache_state(rows, fy_list):
    """How many learning companies have accounts cached for this year window."""
    import auto_train

    fresh = stale = missing = 0
    for r in rows:
        age = auto_train.cache_age_days(r["ticker"], fy_list)
        if age is None:
            missing += 1
        elif age > config.AUTO_CACHE_DAYS:
            stale += 1
        else:
            fresh += 1
    return {"fresh": fresh, "stale": stale, "missing": missing, "cache_days": config.AUTO_CACHE_DAYS}


def feed(rows=None, limit=None):
    """Fetch and cache the accounts of every learning company whose cache is
    missing or stale, one at a time at the polite request pace. Prints a line
    per company for the web app's job log. -> summary dict"""
    import auto_train
    import data_hub

    rows = companies() if rows is None else rows
    write_csv(rows)
    todo = [r for r in rows if auto_train.load_cached(r["ticker"]) is None]
    if limit:
        todo = todo[:limit]
    print(f"[learn] {len(rows)} learning companies; {len(rows) - len(todo)} already cached "
          f"for FY{config.FY_LIST[0]}-FY{config.FY_LIST[-1]}, {len(todo)} to fetch")
    got = thin = failed = 0
    t0 = time.time()
    for i, r in enumerate(todo, 1):
        print(f"[learn] {i}/{len(todo)} {r['name']} ({r['ticker']}) ...", end=" ", flush=True)
        try:
            data = data_hub.fetch_company(r["ticker"], config.FY_LIST)
        except Exception as e:  # noqa: BLE001 - one bad company never stops the feed
            failed += 1
            print(f"FAILED ({type(e).__name__})")
            continue
        auto_train.save_cached(r["ticker"], data)
        ok, fund, px = auto_train.usable(data)
        if ok:
            got += 1
            print(f"ok ({fund} years of accounts, {px} of prices)")
        else:
            thin += 1
            print(f"too little data ({fund} years of accounts, {px} of prices) - cached, adds no rows")
        time.sleep(config.REQUEST_PAUSE)
    print(f"[learn] done in {time.time() - t0:.0f}s: {got} added, {thin} too thin, {failed} failed")
    print(f"[learn] next valuation run trains on {len(rows)} extra companies "
          f"({UNIVERSE_CSV.relative_to(config.PROJECT_ROOT)})")
    return {"companies": len(rows), "fetched": got, "thin": thin, "failed": failed}
