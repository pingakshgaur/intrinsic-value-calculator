# FILE: server/learning_api.py
"""
The web app's side of src/learning.py.

  * status(): how many learning companies there are, by list, and how many
    have their accounts cached for the year window of your last valuation run.
  * after_job(): after every successful valuation run, record what the models
    achieved (training rows, HYBRID MODEL error and mean confidence, ML
    direction) in data/live/learning_history.json, so the page can show
    whether more data actually made the models better - not assume it did.
  * a daily scheduler: after the market closes, start a learning feed (and,
    if you switched it on, a valuation run that trains on the result) when no
    other job is running.
"""

import csv
import logging
import re
import statistics
import threading
import time
from datetime import datetime

import learning
from server import data as D
from server import prefs
from server.live import IST, LIVE, _read_json, _write_json

log = logging.getLogger("web.learning")
SETTINGS = LIVE / "learning.json"
HISTORY = LIVE / "learning_history.json"
DEFAULTS = {"use_in_runs": True, "auto_feed": True, "auto_retrain": False, "feed_after": "16:15", "last_auto": None}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def settings():
    s = dict(DEFAULTS)
    s.update({k: v for k, v in _read_json(SETTINGS, {}).items() if k in DEFAULTS})
    return s


def save_settings(patch):
    s = settings()
    for k in ("use_in_runs", "auto_feed", "auto_retrain"):
        if k in patch:
            s[k] = bool(patch[k])
    if "feed_after" in patch:
        if not _TIME.match(str(patch["feed_after"])):
            raise ValueError("feed_after must be a time like 16:15")
        s["feed_after"] = str(patch["feed_after"])
    _write_json(SETTINGS, s)
    return s


def window(jobs):
    """Year window of the last successful valuation run (the cache is per
    window); the saved run settings when there is none."""
    for j in reversed([jobs.jobs[i] for i in jobs.order]):
        if j.kind == "valuation" and j.status == "succeeded" and "--start-year" in j.args:
            a = j.args
            return int(a[a.index("--start-year") + 1]), int(a[a.index("--end-year") + 1])
    p = prefs.load()
    return p["start_year"], p["end_year"]


def _baseline(jobs):
    """The first time learning is looked at, record the existing report as
    run #1 so the next retrain has something honest to be compared with."""
    if history():
        return
    m = current_metrics()
    if not m.get("report"):
        return
    last = next((jobs.jobs[i] for i in reversed(jobs.order)
                 if jobs.jobs[i].kind == "valuation" and jobs.jobs[i].status == "succeeded"), None)
    args = last.args if last else []
    _write_json(HISTORY, [{**m, "t": m["report"], "job": "baseline", "learning": "--train-universe" in args
                           and "auto" not in args, "auto_train": "auto" in args, "baseline": True}])


def status(jobs):
    _baseline(jobs)
    rows = learning.companies()
    start, end = window(jobs)
    by_list = {}
    for r in rows:
        for tag in r["lists"]:
            by_list[tag] = by_list.get(tag, 0) + 1
    by_sector = {}
    for r in rows:
        by_sector[r["sector"]] = by_sector.get(r["sector"], 0) + 1
    return D.clean({
        "companies": len(rows), "by_list": by_list, "sectors": len(by_sector),
        "by_sector": sorted(([k, v] for k, v in by_sector.items()), key=lambda x: -x[1])[:12],
        "window": [start, end], "cache": learning.cache_state(rows, list(range(start, end + 1))),
        "settings": settings(), "history": history(), "current": current_metrics(),
        "valued": len(D.companies()),
    })


def history():
    h = _read_json(HISTORY, [])
    return h if isinstance(h, list) else []


def current_metrics():
    """What the latest report says about the models, from its output files."""
    out = {"report": D.mtime(D.OUTPUT / "Intrinsic_Value_Data.csv")}
    if not out["report"]:
        return out
    for r in D.read_csv(D.OUTPUT / "metrics_overall.csv"):
        if str(r.get("Model", "")).upper() == "HYBRID MODEL":
            out["hm_medape"] = r.get("MedAPE %")
            out["hm_hit20"] = r.get("Hit +/-20%")
            out["hm_n"] = r.get("N")
    det = D.read_csv(D.OUTPUT / "Hybrid_Model_Detail.csv")
    if det:
        last_fy = max(str(r.get("Financial Year")) for r in det)
        conf = [r["Confidence"] for r in det if str(r.get("Financial Year")) == last_fy and isinstance(r.get("Confidence"), float)]
        out["hm_confidence"] = statistics.mean(conf) if conf else None
        out["hm_fy"] = last_fy
        allc = [r["Confidence"] for r in det if isinstance(r.get("Confidence"), float)]
        out["hm_confidence_all"] = statistics.mean(allc) if allc else None
    ml = D.read_csv(D.OUTPUT / "ml_metrics.csv")
    ok = [r for r in ml if r.get("status") == "ok" and str(r.get("leaked")).lower() != "true"]
    if ok:
        out["ml_direction"] = 100 * statistics.mean(r["directional_accuracy"] for r in ok
                                                    if isinstance(r.get("directional_accuracy"), float))
        out["ml_train_rows"] = max(r["n_train"] for r in ok if isinstance(r.get("n_train"), float))
    p = D.OUTPUT / "ml_dataset.csv"
    if p.exists():
        with open(p, encoding="utf-8-sig", newline="") as f:
            rd = csv.DictReader(f)
            labelled = companies = 0
            names = set()
            for r in rd:
                names.add(r.get("company"))
                if r.get("label") not in (None, "", "nan"):
                    labelled += 1
            companies = len(names)
        out["labelled_rows"], out["training_companies"] = labelled, companies
    return D.clean(out)


def after_job(job, jobs):
    if job.status != "succeeded":
        return
    if job.kind == "valuation":
        m = current_metrics()
        h = history()
        h.append({**m, "t": time.time(), "job": job.id, "learning": "--train-universe" in job.args,
                  "auto_train": "auto" in job.args})
        _write_json(HISTORY, h[-200:])
    elif job.kind == "learn" and (job.opts or {}).get("retrain"):
        try:
            jobs.start("valuation", {"learning": True, "start_year": job.opts.get("start_year"),
                                     "end_year": job.opts.get("end_year")})
        except (RuntimeError, ValueError):
            pass


def _scheduler(jobs):
    while True:
        time.sleep(60)
        try:
            s = settings()
            now = datetime.now(IST)
            today = now.strftime("%Y-%m-%d")
            if not s["auto_feed"] or s["last_auto"] == today or now.strftime("%H:%M") < s["feed_after"]:
                continue
            if jobs.active():
                continue
            start, end = window(jobs)
            jobs.start("learn", {"retrain": s["auto_retrain"], "start_year": start, "end_year": end, "auto": True})
            _write_json(SETTINGS, {**s, "last_auto": today})
        except Exception:
            log.exception("learning scheduler tick failed")


def start_scheduler(jobs):
    threading.Thread(target=_scheduler, args=(jobs,), daemon=True, name="learning-scheduler").start()


def learning_csv(exclude=None):
    """Rebuild the learning pool file for a run, minus the companies the run
    values directly (`exclude`: rows with a name and a ticker). -> absolute path"""
    return str(learning.write_csv(learning.companies(exclude=exclude)))
