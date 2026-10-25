"""
Auto-train: grow the ML training universe one company at a time until the
Hybrid is confident enough, then stop.

    python run.py --train-universe auto

WHAT IT DOES

  1. CANDIDATES. Reads NSE's public lists:
       ind_niftytotalmarket_list.csv   ~750 companies with their industry
       ind_nifty100 / midcap150 / smallcap250   -> Large / Mid / Small
       EQUITY_L.csv                    the official NSE date of listing
     and keeps only companies listed on NSE at least AUTO_MIN_LISTED_YEARS
     ago, outside Financial Services (unless asked), and not already in your
     main list.

  2. SECTORS. Ranks sectors and keeps the best AUTO_SECTORS. "performance"
     ranks by the median share-price return of each sector's long-listed
     companies over the AUTO_RANK_YEARS that END WHERE THE VALUATION WINDOW
     STARTS. Ranking on the most recent winners would use hindsight: the
     training set would be chosen for having done well during the very years
     the models are scored on. "breadth" ranks by how many long-listed
     companies a sector has instead.

  3. ORDER. Companies are drawn AT RANDOM within each sector and the sectors
     take turns, so stopping early still leaves a balanced sample. The seed
     is printed and logged; --auto-seed replays an exact draw.

  4. LOOP. Each company is fetched from Yahoo Finance (cached locally for
     AUTO_CACHE_DAYS), added to the training universe, and every AUTO_BATCH
     companies the ML models are retrained and the Hybrid is re-scored on
     YOUR companies. The meter is the Hybrid's average confidence.

  5. STOP at the first of:
       confidence >= target                      ("High" reached)
       AUTO_PATIENCE retrains in a row without gaining AUTO_MIN_GAIN points
                                                 (optional; off by default)
       AUTO_MAX_COMPANIES learned
       candidates exhausted
       you press stop

WHY IT CAN PLATEAU BELOW "HIGH"

More training companies sharpen the ML component, and through it the
Hybrid. They cannot remove the uncertainty that is genuinely in the market:
if one-year-ahead prices really do scatter +/-30% around any fundamental
value, no amount of data makes a "within 20%" prediction 60% likely. The
plateau rule exists so the program recognises that and stops, instead of
fetching forever.

WHY NOT SCREENER.IN

Screener.in's robots.txt disallows its paginated and sorted pages and its
terms forbid copying its material, so it is not scraped. Everything here
comes from NSE's published files and Yahoo Finance, the same public sources
the rest of the program already uses.

CONTROLS

A Controls object is shared with whoever drives the run - the terminal
(keys) or the GUI (buttons): pause/resume, skip this company, skip this
sector, retrain now, raise/lower the target, stop and finish.
"""

import csv
import datetime as dt
import io
import json
import logging
import math
import pickle
import random
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field

import config
import yf_source

log = logging.getLogger("auto_train")

INDEX_URL = "https://www.niftyindices.com/IndexConstituent/"
TOTAL_MARKET = "ind_niftytotalmarket_list.csv"
CAP_FILES = {
    "ind_nifty100list.csv": "Large",
    "ind_niftymidcap150list.csv": "Mid",
    "ind_niftysmallcap250list.csv": "Small",
}
EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

# NSE industry -> the sector names used in data/companies.csv, so the ML
# sector indicators line up between the main list and the training list.
SECTOR_MAP = {
    "Automobile and Auto Components": "Automobiles and Auto Components",
    "Fast Moving Consumer Goods": "Fast Moving Consumer Goods",
    "Information Technology": "Information Technology",
    "Healthcare": "Healthcare and Medical Devices",
    "Metals & Mining": "Metals and Mining",
    "Power": "Power and Renewable Energy",
}
FINANCIAL = "Financial Services"


# ================================================================= options
@dataclass
class Options:
    target: float = None
    max_companies: int = None
    sectors: int = None
    min_listed_years: int = None
    batch: int = None
    patience: int = None
    min_gain: float = None
    sector_rank: str = None
    rank_years: int = None
    include_financials: bool = None
    use_cache: bool = True
    seed: int = None
    exclude_tickers: set = field(default_factory=set)

    def __post_init__(self):
        if self.seed is None:
            # a fresh random draw every run - printed, so it can be replayed
            self.seed = random.SystemRandom().randrange(1, 1_000_000)
        defaults = {
            "target": getattr(config, "AUTO_TARGET", None)
            or getattr(config, "HYBRID_CONF_HIGH", 60),
            "max_companies": config.AUTO_MAX_COMPANIES,
            "sectors": config.AUTO_SECTORS,
            "min_listed_years": config.AUTO_MIN_LISTED_YEARS,
            "batch": config.AUTO_BATCH,
            "patience": config.AUTO_PATIENCE,
            "min_gain": config.AUTO_MIN_GAIN,
            "sector_rank": config.AUTO_SECTOR_RANK,
            "rank_years": config.AUTO_RANK_YEARS,
            "include_financials": config.AUTO_INCLUDE_FINANCIALS,
        }
        for k, v in defaults.items():
            if getattr(self, k) is None:
                setattr(self, k, v)


# ================================================================ controls
class Controls:
    """Thread-safe switches shared between the engine and its front end."""

    def __init__(self, target):
        self._lock = threading.Lock()
        self.target = float(target)
        self.paused = False
        self.stop_requested = False
        self.skip_company = False
        self.retrain_now = False
        self.skip_sectors = set()
        self.current_sector = None

    def toggle_pause(self):
        with self._lock:
            self.paused = not self.paused
            return self.paused

    def stop(self):
        with self._lock:
            self.stop_requested = True
            self.paused = False

    def skip(self):
        with self._lock:
            self.skip_company = True

    def skip_sector(self):
        with self._lock:
            if self.current_sector:
                self.skip_sectors.add(self.current_sector)
            self.skip_company = True

    def retrain(self):
        with self._lock:
            self.retrain_now = True

    def adjust_target(self, delta):
        with self._lock:
            self.target = max(5.0, min(95.0, self.target + delta))
            return self.target

    def take(self, name):
        """Read-and-clear a one-shot flag."""
        with self._lock:
            v = getattr(self, name)
            setattr(self, name, False)
            return v


# ============================================================ public lists
def _cache_dir(*parts):
    p = config.CACHE_DIR.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _download(url, name, max_age_days=1):
    """Text of a public CSV, cached under .cache/nse for a day."""
    path = _cache_dir("nse") / name
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400:
        return path.read_text(encoding="utf-8-sig")
    import requests

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig")
    path.write_text(text, encoding="utf-8")
    return text


def _rows(text):
    return [
        {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        for row in csv.DictReader(io.StringIO(text))
    ]


def _listing_dates():
    out = {}
    for row in _rows(_download(EQUITY_LIST_URL, "EQUITY_L.csv")):
        try:
            out[row["SYMBOL"].upper()] = dt.datetime.strptime(
                row["DATE OF LISTING"], "%d-%b-%Y"
            ).date()
        except (KeyError, ValueError):
            continue
    return out


def eligible_companies(opts, emit):
    """-> list of candidate dicts that pass the listing-age and sector rules."""
    universe = _rows(_download(INDEX_URL + TOTAL_MARKET, TOTAL_MARKET))
    caps = {}
    for fname, label in CAP_FILES.items():
        for row in _rows(_download(INDEX_URL + fname, fname)):
            caps.setdefault(row["Symbol"].upper(), label)
    listed = _listing_dates()

    cutoff = dt.date.today().replace(year=dt.date.today().year - opts.min_listed_years)
    out, dropped = [], {"listed too recently": 0, "financial services": 0, "already in your list": 0, "no listing date": 0}
    for row in universe:
        sym = row.get("Symbol", "").upper()
        if not sym or row.get("Series", "EQ") != "EQ":
            continue
        if sym in opts.exclude_tickers:
            dropped["already in your list"] += 1
            continue
        industry = row.get("Industry", "")
        if industry == FINANCIAL and not opts.include_financials:
            dropped["financial services"] += 1
            continue
        date = listed.get(sym)
        if date is None:
            dropped["no listing date"] += 1
            continue
        if date > cutoff:
            dropped["listed too recently"] += 1
            continue
        out.append(
            {
                "name": row["Company Name"],
                "sector": SECTOR_MAP.get(industry, industry),
                "cap": caps.get(sym, "Small"),
                "ticker": f"{sym}.NS",
                "listed": date.isoformat(),
            }
        )
    emit(
        "status",
        message=(
            f"{len(out)} of {len(universe)} NIFTY Total Market companies are eligible "
            f"(listed on NSE before {cutoff:%d %b %Y}); skipped "
            + ", ".join(f"{n} {why}" for why, n in dropped.items() if n)
        ),
    )
    return out


def _rank_window():
    """The AUTO_RANK_YEARS ending where the valuation window starts."""
    from fy_utils import fy_window

    end = fy_window(min(config.FY_LIST))[0]
    start = end.replace(year=end.year - config.AUTO_RANK_YEARS)
    return start, end


def rank_sectors(cands, opts, emit):
    """-> [(sector, score, n)] best first. score is a median return or a count."""
    by_sector = {}
    for c in cands:
        by_sector.setdefault(c["sector"], []).append(c)

    if opts.sector_rank == "performance":
        start, end = _rank_window()
        key = f"rank_{start}_{end}_{len(cands)}.json"
        path = _cache_dir("nse") / key
        rets = None
        if path.exists():
            rets = json.loads(path.read_text())
        else:
            emit(
                "status",
                message=(
                    f"ranking sectors by median share-price return "
                    f"{start:%b %Y} - {end:%b %Y} (before the valuation window, so "
                    f"no hindsight) ..."
                ),
            )
            try:
                import yfinance as yf

                tickers = [c["ticker"] for c in cands]
                px = yf.download(
                    tickers,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    interval="1mo",
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )["Close"]
                rets = {}
                for t in tickers:
                    if t not in px:
                        continue
                    s = px[t].dropna()
                    if len(s) >= 12 and s.iloc[0] > 0:
                        rets[t] = float(s.iloc[-1] / s.iloc[0] - 1)
                path.write_text(json.dumps(rets))
            except Exception as e:
                log.exception("sector ranking download failed")
                emit(
                    "status",
                    message=f"price download for ranking failed ({type(e).__name__}); "
                    f"falling back to ranking by breadth",
                )
                rets = None

        if rets:
            ranked = []
            for s, cs in by_sector.items():
                vals = [rets[c["ticker"]] for c in cs if c["ticker"] in rets]
                if len(vals) >= 3:
                    ranked.append((s, statistics.median(vals), len(cs)))
            ranked.sort(key=lambda x: -x[1])
            return ranked

    ranked = [(s, float(len(cs)), len(cs)) for s, cs in by_sector.items()]
    ranked.sort(key=lambda x: -x[1])
    return ranked


def build_queue(opts, emit):
    """-> (ordered candidate list, chosen sector table)."""
    cands = eligible_companies(opts, emit)
    ranked = rank_sectors(cands, opts, emit)[: opts.sectors]
    chosen = [s for s, _, _ in ranked]

    # RANDOM draw inside each sector. The seed is printed and logged, so any
    # run can be reproduced exactly with --auto-seed.
    rng = random.Random(opts.seed)
    pools = {}
    for s in chosen:
        pool = [c for c in cands if c["sector"] == s]
        rng.shuffle(pool)
        pools[s] = pool
    queue = []
    while any(pools.values()):
        for s in chosen:
            if pools[s]:
                queue.append(pools[s].pop(0))
    return queue, ranked


# ===================================================================== fetch
def _cache_path(ticker):
    fys = sorted(config.FY_LIST)
    return _cache_dir("train_cache") / f"{ticker}_{fys[0]}_{fys[-1]}.pkl"


def load_cached(ticker):
    path = _cache_path(ticker)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > config.AUTO_CACHE_DAYS * 86400:
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def save_cached(ticker, data):
    try:
        with open(_cache_path(ticker), "wb") as f:
            pickle.dump(data, f)
    except Exception:
        log.exception("could not cache %s", ticker)


def usable(data):
    """Enough to contribute labelled ML rows: two years of fundamentals and price."""
    years = data.get("years", {})
    fund = sum(1 for d in years.values() if d.get("ebit") is not None)
    px = sum(1 for d in years.values() if d.get("price"))
    return fund >= 2 and px >= 2, fund, px


# ==================================================================== engine
class AutoTrainer:
    """
    on_event(kind, **info) is called for everything worth showing. The engine
    never prints; the terminal meter and the GUI each render events their own
    way.
    """

    def __init__(self, opts=None, controls=None, on_event=None):
        self.opts = opts or Options()
        self.controls = controls or Controls(self.opts.target)
        self.on_event = on_event or (lambda kind, **info: None)
        self.state = {
            "learned": 0,
            "max": self.opts.max_companies,
            "confidence": 0.0,
            "hit20": 0.0,
            "labelled": 0,
            "history": [],
            "current": "",
            "sector": "",
            "phase": "starting",
        }

    def emit(self, kind, **info):
        self.state.update({k: v for k, v in info.items() if k in self.state})
        self.state["target"] = self.controls.target
        try:
            self.on_event(kind, **info)
        except Exception:
            log.exception("auto-train event handler failed")

    # -------------------------------------------------------------- fetching
    def _fetch(self, cand):
        """-> (data or None, how). Abandons the download on skip/stop."""
        if self.opts.use_cache:
            data = load_cached(cand["ticker"])
            if data is not None:
                return data, "cached"

        box = {}

        def work():
            try:
                box["data"] = yf_source.fetch_company(cand["ticker"], config.FY_LIST)
            except Exception as e:  # noqa: BLE001
                box["err"] = e

        t = threading.Thread(target=work, daemon=True)
        t.start()
        while t.is_alive():
            t.join(0.2)
            if self.controls.stop_requested or self.controls.take("skip_company"):
                return None, "skipped"
        if "err" in box:
            return None, f"download failed ({type(box['err']).__name__})"
        save_cached(cand["ticker"], box["data"])
        time.sleep(config.REQUEST_PAUSE)
        return box["data"], "downloaded"

    def _wait_if_paused(self):
        announced = False
        while self.controls.paused and not self.controls.stop_requested:
            if not announced:
                self.emit("paused", phase="paused")
                announced = True
            time.sleep(0.2)
        if announced:
            self.emit("resumed", phase="fetching")

    # -------------------------------------------------------------- scoring
    def _score(self, train_universe, evaluate):
        self.emit("training", phase="training")
        m = evaluate(train_universe)
        self.state["history"].append(m["confidence"])
        self.emit(
            "score",
            phase="fetching",
            confidence=m["confidence"],
            hit20=m["hit20"],
            labelled=m["labelled"],
            ml_direction=m.get("ml_direction"),
        )
        return m

    def _plateaued(self):
        h, p = self.state["history"], self.opts.patience
        if p <= 0 or len(h) <= p:  # 0 = rule switched off
            return False
        return max(h[-p:]) < max(h[:-p]) + self.opts.min_gain

    # ------------------------------------------------------------------ run
    def run(self, train_universe, evaluate):
        """
        Grow train_universe in place. evaluate(train_universe) must retrain
        and return {confidence, hit20, labelled, ...}. -> summary dict.
        """
        opts, ctl = self.opts, self.controls
        learned, log_rows, since_score = [], [], 0
        reason = "candidates exhausted"

        try:
            queue, ranked = build_queue(opts, self.emit)
        except Exception as e:
            log.exception("could not build the candidate list")
            self.emit("error", message=f"could not read the NSE lists: {type(e).__name__}: {e}")
            return {"reason": "no candidates", "learned": []}

        self.emit(
            "plan",
            sectors=ranked,
            candidates=len(queue),
            rank=opts.sector_rank,
            max=opts.max_companies,
            seed=opts.seed,
        )
        if not queue:
            return {"reason": "no candidates", "learned": []}

        m = self._score(train_universe, evaluate)
        log_rows.append(self._log_row(0, m))

        try:
            for cand in queue:
                self._wait_if_paused()
                if ctl.stop_requested:
                    reason = "stopped by you"
                    break
                if cand["sector"] in ctl.skip_sectors:
                    continue
                if cand["name"] in train_universe:
                    continue

                ctl.current_sector = cand["sector"]
                ctl.take("skip_company")
                self.emit(
                    "fetching",
                    phase="fetching",
                    current=cand["name"],
                    sector=cand["sector"],
                )
                data, how = self._fetch(cand)
                if ctl.stop_requested:
                    reason = "stopped by you"
                    break
                if data is None:
                    self.emit("skipped", name=cand["name"], why=how)
                    continue
                ok, fund, px = usable(data)
                if not ok:
                    self.emit(
                        "skipped",
                        name=cand["name"],
                        why=f"too little data ({fund} years of accounts, {px} of prices)",
                    )
                    continue

                train_universe[cand["name"]] = {
                    "sector": cand["sector"],
                    "cap": cand["cap"],
                    "ticker": data.get("ticker", cand["ticker"]),
                    "data": data,
                }
                learned.append(cand)
                since_score += 1
                self.emit(
                    "learned",
                    learned=len(learned),
                    name=cand["name"],
                    sector=cand["sector"],
                    cap=cand["cap"],
                    ticker=cand["ticker"],
                    listed=cand["listed"],
                    fund=fund,
                    px=px,
                    how=how,
                )

                if since_score >= opts.batch or ctl.take("retrain_now"):
                    since_score = 0
                    m = self._score(train_universe, evaluate)
                    log_rows.append(self._log_row(len(learned), m))
                    if m["confidence"] >= ctl.target:
                        reason = f"confidence reached the target ({ctl.target:.0f})"
                        break
                    if self._plateaued():
                        reason = (
                            f"learning plateaued - {opts.patience} retrains in a row "
                            f"gained less than {opts.min_gain} points"
                        )
                        break
                if len(learned) >= opts.max_companies:
                    reason = f"reached the limit of {opts.max_companies} companies"
                    break
        except KeyboardInterrupt:
            reason = "stopped by you (Ctrl+C)"

        if since_score:
            m = self._score(train_universe, evaluate)
            log_rows.append(self._log_row(len(learned), m))

        paths = self._write(learned, log_rows)
        self.emit("done", phase="done", reason=reason, learned=len(learned), paths=paths)
        return {"reason": reason, "learned": learned, "paths": paths, "final": m}

    @staticmethod
    def _log_row(n, m):
        return {
            "companies_learned": n,
            "labelled_rows": m.get("labelled"),
            "hybrid_confidence": round(m["confidence"], 2),
            "hybrid_hit_within_20pct": round(m["hit20"], 2),
            "ml_directional_accuracy": m.get("ml_direction"),
            "seconds_to_retrain": round(m.get("seconds", 0.0), 1),
        }

    @staticmethod
    def _write(learned, log_rows):
        paths = []
        if learned:
            p = config.DATA_DIR / "auto_training_universe.csv"
            with open(p, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(
                    f, fieldnames=["company name", "sector name", "market cap", "ticker"]
                )
                w.writeheader()
                for c in learned:
                    w.writerow(
                        {
                            "company name": c["name"],
                            "sector name": c["sector"],
                            "market cap": c["cap"],
                            "ticker": c["ticker"],
                        }
                    )
            paths.append(p)
        if log_rows:
            config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            p = config.OUTPUT_DIR / "auto_train_log.csv"
            with open(p, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(log_rows[0].keys()))
                w.writeheader()
                w.writerows(log_rows)
            paths.append(p)
        return paths


# ================================================================ web meter
class WebMeter:
    """
    The browser's view of an auto-train run in a child process.

    Events go out as one JSON line each on the real stdout ("[auto-event]
    {...}"), which the web server already streams to the page. Commands come
    back through a small file the server appends to: one JSON object per line,
    {"action": "pause" | "skip" | "skip_sector" | "retrain" | "target" |
    "stop", "value": ...}. Same Controls object the terminal keys drive.
    """

    def __init__(self, controls, control_file):
        self.controls = controls
        self.path = control_file
        self._stop = threading.Event()
        self._offset = 0
        self.out = sys.__stdout__ or sys.stdout

    def start_keys(self):
        threading.Thread(target=self._poll, daemon=True).start()
        return True

    def stop_keys(self):
        self._stop.set()

    def _poll(self):
        import json

        while not self._stop.is_set():
            try:
                with open(self.path, encoding="utf-8") as f:
                    f.seek(self._offset)
                    chunk = f.read()
                    self._offset = f.tell()
            except OSError:
                chunk = ""
            for line in chunk.splitlines():
                try:
                    cmd = json.loads(line)
                except ValueError:
                    continue
                self._apply(cmd.get("action"), cmd.get("value"))
            time.sleep(0.4)

    def _apply(self, action, value):
        c = self.controls
        if action == "pause":
            paused = c.toggle_pause()
            self("status", message="paused" if paused else "resuming")
        elif action == "skip":
            c.skip()
            self("status", message="skipping this company")
        elif action == "skip_sector":
            c.skip_sector()
            self("status", message=f"skipping the rest of {c.current_sector}")
        elif action == "retrain":
            c.retrain()
            self("status", message="will retrain after this company")
        elif action == "target":
            try:
                t = c.adjust_target(float(value or 0))
            except (TypeError, ValueError):
                return
            self("status", message=f"target changed to {t:.0f}")
        elif action == "stop":
            c.stop()
            self("status", message="finishing with what has been learned")

    def __call__(self, kind, **info):
        import json

        payload = {"kind": kind, "target": self.controls.target, "paused": self.controls.paused, **info}
        try:
            text = json.dumps(payload, default=str)
        except (TypeError, ValueError):
            text = json.dumps({"kind": kind, "message": str(info)[:300]})
        print(f"[auto-event] {text}", file=self.out, flush=True)


# ============================================================ terminal meter
class TerminalMeter:
    """
    Renders engine events in a terminal and turns keypresses into controls.

        P pause/resume   S skip company   X skip sector   R retrain now
        + / - target     Q stop and finish
    """

    KEYS = "[P]ause  [S]kip  [X] skip sector  [R]etrain now  [+/-] target  [Q] stop & finish"

    def __init__(self, controls):
        self.controls = controls
        self.state = {}
        self._line_open = False
        self._stop_keys = threading.Event()
        # The console itself, not sys.stdout: the pipeline silences stdout while
        # it retrains, and keypress feedback must still get through.
        self.out = sys.__stdout__ or sys.stdout

    # ---- keys (Windows console; elsewhere only Ctrl+C works) ----
    def start_keys(self):
        try:
            import msvcrt  # noqa: F401
        except ImportError:
            return False
        threading.Thread(target=self._key_loop, daemon=True).start()
        return True

    def stop_keys(self):
        self._stop_keys.set()

    def _key_loop(self):
        import msvcrt

        while not self._stop_keys.is_set():
            if not msvcrt.kbhit():
                time.sleep(0.1)
                continue
            k = msvcrt.getwch().lower()
            c = self.controls
            if k == "p":
                self._say("paused - press P to resume" if c.toggle_pause() else "resuming")
            elif k == "s":
                c.skip()
                self._say("skipping this company")
            elif k == "x":
                c.skip_sector()
                self._say(f"skipping the rest of {c.current_sector}")
            elif k == "r":
                c.retrain()
                self._say("will retrain after this company")
            elif k in "+=":
                self._say(f"target raised to {c.adjust_target(+5):.0f}")
            elif k in "-_":
                self._say(f"target lowered to {c.adjust_target(-5):.0f}")
            elif k == "q":
                c.stop()
                self._say("stopping - finishing with what has been learned")

    # ---- rendering ----
    def _say(self, text):
        if self._line_open:
            print(file=self.out)
            self._line_open = False
        print(f"[auto] {text}", file=self.out, flush=True)
        self._meter()

    def _bar(self, value, target, width=30):
        filled = int(round(width * min(value, 100) / 100))
        mark = min(width - 1, int(round(width * target / 100)))
        cells = ["#" if i < filled else "-" for i in range(width)]
        cells[mark] = "|"
        return "".join(cells)

    def _meter(self):
        s = self.state
        if "confidence" not in s:  # nothing to show before the first score
            return
        conf, tgt = s.get("confidence", 0.0), self.controls.target
        line = (
            f"\r  confidence [{self._bar(conf, tgt)}] {conf:5.1f}/{tgt:.0f}"
            f"   learned {s.get('learned', 0)}/{s.get('max', 0)}"
            f"   {s.get('phase', '')}: {str(s.get('current', ''))[:34]:34s}"
        )
        print(line, end="", file=self.out, flush=True)
        self._line_open = True

    def __call__(self, kind, **info):
        self.state.update(info)
        self.state.setdefault("max", config.AUTO_MAX_COMPANIES)
        if kind == "status":
            self._say(info["message"])
        elif kind == "error":
            self._say(f"ERROR: {info['message']}")
        elif kind == "plan":
            lines = [
                f"training plan: {self.state['max']} RANDOM companies from the top "
                f"{len(info['sectors'])} sectors ({info['candidates']} candidates, "
                f"ranked by {info['rank']}; random seed {info['seed']} - replay "
                f"this exact draw with --auto-seed {info['seed']})"
            ]
            for s, score, n in info["sectors"]:
                metric = f"{score:+.0%} median return" if info["rank"] == "performance" else f"{n} companies"
                lines.append(f"   {s:42s} {metric}")
            lines.append(self.KEYS)
            self._say("\n".join(lines))
        elif kind == "score":
            self.state["current"] = ""
            hist = self.state.get("history_text", "")
            self.state["history_text"] = (hist + f" {info['confidence']:.0f}").strip()
            self._say(
                f"retrained on {info['labelled']} labelled rows -> Ensemble confidence "
                f"{info['confidence']:.1f} (actual within 20%: {info['hit20']:.0f}%)"
                f"   history: {self.state['history_text']}"
            )
        elif kind == "training":
            self.state["current"] = "retraining models ..."
            self._meter()
        elif kind == "skipped":
            self._say(f"skipped {info['name']}: {info['why']}")
        elif kind == "learned":
            # one permanent line per company drawn from the market
            self.state["current"] = ""
            n = f"{info['learned']}/{self.state['max']}"
            self._say(
                f"learn {n:>7}  {info['name'][:40]:40s} {info['ticker']:16s} "
                f"{info['sector'][:30]:30s} {info['cap']:5s}  listed {info['listed'][:4]}  "
                f"accounts {info['fund']}y prices {info['px']}y  ({info['how']})"
            )
        elif kind == "fetching":
            self.state["current"] = f"downloading {info['current']}"
            self._meter()
        elif kind == "paused":
            self.state["current"] = "PAUSED - press P"
            self._meter()
        elif kind == "done":
            self.state["current"] = ""
            self._say(f"finished: {info['reason']}; {info['learned']} companies learned")
            # the run carries on (valuation, export) on fresh lines
            self._line_open = False
            print(file=self.out)
            for p in info.get("paths", []):
                print(f"[auto] wrote {p}", file=self.out)
