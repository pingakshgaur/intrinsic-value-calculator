# FILE: server/jobs.py
"""
Background jobs: each one is a child `python run.py ...` process.

One job at a time. The pipeline downloads from rate-limited sources and the
agents pace themselves against free LLM quotas; two runs in parallel would
only fight over both. Output is captured line by line so the browser can
follow it live, and the last jobs are remembered in output/web_jobs.json so
a page refresh (or a server restart) still shows what happened.

Auto-train runs get a control file the browser writes commands into
(pause, skip, skip sector, retrain, target, stop); see auto_train.WebMeter.
"""

import csv
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid

from server import learning_api, prefs
from server.data import OUTPUT, ROOT, companies

log = logging.getLogger("web.jobs")
MAX_LINES = 20000
HISTORY = OUTPUT / "web_jobs.json"
WORK = OUTPUT / "web_runs"
TICKERS = re.compile(r"^[A-Za-z0-9&._\-]+(,[A-Za-z0-9&._\-]+)*$")
CONTROL_ACTIONS = {"pause", "skip", "skip_sector", "retrain", "target", "stop"}


def _selection_csv(job_id, exclude):
    """Write the companies this run includes; -> path or None (= everyone)."""
    exclude = {str(x) for x in (exclude or [])}
    if not exclude:
        return None
    rows = [c for c in companies() if c["name"] not in exclude]
    if not rows:
        raise ValueError("every company is unticked - include at least one")
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"companies_{job_id}.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["company name", "sector name", "market cap", "ticker"])
        for c in rows:
            w.writerow([c["name"], c["sector"], c["cap"], c["ticker"]])
    return str(path)


def _watchlist_csv(job_id, list_id):
    """Write a watchlist's companies as a run input; -> (path, list name). Every
    company on the list is researched, covered by the valuation report or not."""
    from server import live

    try:
        name, rows = live.list_companies(list_id)
    except KeyError:
        raise ValueError(f"no watchlist {list_id}")
    if not rows:
        raise ValueError(f"the watchlist '{name}' has no companies yet")
    known = {c["ticker"]: c for c in companies() if c.get("ticker")}
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"watchlist_{job_id}.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["company name", "sector name", "market cap", "ticker"])
        for r in rows:
            k = known.get(r["ticker"], {})
            w.writerow([k.get("name") or r["name"], k.get("sector") or r["sector"] or "Unclassified",
                        k.get("cap") or r["cap"], r["ticker"]])
    return str(path), name


def build_args(kind, opts, job_id="x"):
    """Validated command line for a job kind. Raises ValueError on bad input."""
    opts = opts or {}
    a = []
    if kind in ("valuation", "screen"):
        p = prefs.load()
        for k in ("start_year", "end_year"):
            if opts.get(k):
                p[k] = int(opts[k])
        p = prefs.clean(p)
        if kind == "screen":
            a += ["--screen-only", "--start-year", str(p["start_year"]), "--end-year", str(p["end_year"])]
            a += ["--screening", p["screening"] if p["screening"] != "off" else "enforce",
                  "--min-complete-fy", str(p["min_complete_fy"]), "--min-benchmark-fy", str(p["min_benchmark_fy"])]
        else:
            a += prefs.to_args(p)
        if opts.get("watchlist") and not opts.get("offline"):
            sel, opts["watchlist_name"] = _watchlist_csv(job_id, str(opts["watchlist"]))
        else:
            sel = _selection_csv(job_id, opts.get("exclude"))
        if sel:
            a += ["--input", sel]
        if opts.get("offline"):
            a.append("--offline")
        auto = opts.get("auto_train")
        if kind == "valuation" and isinstance(auto, dict):
            if opts.get("offline"):
                raise ValueError("auto-train downloads real companies; switch off offline test data")
            WORK.mkdir(parents=True, exist_ok=True)
            ctl = WORK / f"control_{job_id}.jsonl"
            ctl.write_text("", encoding="utf-8")
            a += ["--train-universe", "auto", "--auto-control", str(ctl)]
            for key, flag, lo, hi in (("target", "--auto-target", 5, 95), ("max", "--auto-max", 1, 1000),
                                      ("sectors", "--auto-sectors", 1, 30), ("min_listed_years", "--auto-min-listed-years", 1, 40)):
                if auto.get(key) is not None:
                    a += [flag, str(max(lo, min(hi, int(auto[key]))))]
        elif kind == "valuation" and not opts.get("offline"):
            use = opts.get("learning")
            if use is None:
                use = learning_api.settings()["use_in_runs"]
            if use:
                a += ["--train-universe", learning_api.learning_csv()]
    elif kind == "learn":
        if opts.get("offline"):
            raise ValueError("the learning feed downloads real companies; switch off offline test data")
        p = prefs.load()
        start, end = int(opts.get("start_year") or p["start_year"]), int(opts.get("end_year") or p["end_year"])
        a += ["--learn", "--start-year", str(min(start, end)), "--end-year", str(max(start, end)),
              "--exchange", p["exchange"]]
    elif kind == "agents":
        a.append("--agents")
        if opts.get("quick"):
            a.append("--quick")
        if opts.get("no_llm"):
            a.append("--no-llm")
        if opts.get("offline"):
            a.append("--offline")
        if opts.get("watchlist") and not opts.get("offline"):
            path, name = _watchlist_csv(job_id, str(opts["watchlist"]))
            a += ["--input", path]
            opts["watchlist_name"] = name
        t = (opts.get("tickers") or "").replace(" ", "")
        if t:
            if not TICKERS.match(t):
                raise ValueError("tickers must be a comma-separated list like HAL,BEL")
            a += ["--tickers", t]
    elif kind == "llm_check":
        a += ["--agents", "--llm-check"]
    else:
        raise ValueError(f"unknown job kind '{kind}'")
    return a


class Job:
    def __init__(self, kind, opts):
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.args = []
        self.opts = opts
        self.status = "queued"
        self.started = time.time()
        self.finished = None
        self.returncode = None
        self.lines = []
        self.proc = None
        self.control = None
        self.lock = threading.Lock()

    def summary(self, with_tail=0):
        d = {
            "id": self.id, "kind": self.kind, "args": self.args, "opts": self.opts,
            "status": self.status, "started": self.started, "finished": self.finished,
            "returncode": self.returncode, "lines": len(self.lines),
            "controllable": bool(self.control) and self.status == "running",
        }
        if with_tail:
            d["tail"] = self.lines[-with_tail:]
        return d


class JobManager:
    def __init__(self):
        self.jobs = {}
        self.order = []
        self.lock = threading.Lock()
        self.on_done = []  # callbacks(job) after every job ends
        self._load()

    def _load(self):
        try:
            for d in json.loads(HISTORY.read_text(encoding="utf-8"))[-30:]:
                j = Job(d["kind"], d.get("opts"))
                j.id, j.status, j.started, j.args = d["id"], d["status"], d["started"], d.get("args", [])
                j.finished, j.returncode = d.get("finished"), d.get("returncode")
                if j.status in ("running", "queued"):
                    j.status = "interrupted"
                j.lines = d.get("tail", [])
                self.jobs[j.id] = j
                self.order.append(j.id)
        except (OSError, ValueError, KeyError):
            pass

    def _save(self):
        try:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            data = [self.jobs[i].summary(with_tail=400) for i in self.order[-30:]]
            HISTORY.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def active(self):
        with self.lock:
            for i in reversed(self.order):
                j = self.jobs[i]
                if j.status in ("queued", "running"):
                    return j
        return None

    def start(self, kind, opts):
        if self.active():
            raise RuntimeError("another job is still running - wait for it or cancel it")
        if kind == "learn" and not (opts or {}).get("start_year"):
            start, end = learning_api.window(self)
            opts = {**(opts or {}), "start_year": start, "end_year": end}
        job = Job(kind, opts)
        job.args = build_args(kind, opts, job.id)
        if "--auto-control" in job.args:
            job.control = job.args[job.args.index("--auto-control") + 1]
        with self.lock:
            self.jobs[job.id] = job
            self.order.append(job.id)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job):
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", MPLBACKEND="Agg", NO_COLOR="1", PYTHON_COLORS="0")
        # the installed app is one executable that takes run.py's arguments
        cmd = [sys.executable, *job.args] if getattr(sys, "frozen", False) else [sys.executable, "-u", str(ROOT / "run.py"), *job.args]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            job.proc = subprocess.Popen(
                cmd, cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=flags,
            )
        except OSError as e:
            job.status, job.finished = "failed", time.time()
            job.lines.append(f"could not start: {e}")
            self._save()
            return
        job.status = "running"
        job.lines.append("$ python run.py " + " ".join(job.args))
        for line in job.proc.stdout:
            with job.lock:
                job.lines.append(line.rstrip("\r\n"))
                if len(job.lines) > MAX_LINES:
                    del job.lines[: len(job.lines) - MAX_LINES]
        job.returncode = job.proc.wait()
        job.finished = time.time()
        if job.status != "cancelled":
            job.status = "succeeded" if job.returncode == 0 else "failed"
        job.lines.append(f"[exit code {job.returncode}]")
        self._save()
        for cb in self.on_done:
            try:
                cb(job)
            except Exception:
                log.exception("job hook failed after %s", job.id)

    def control(self, job_id, action, value=None):
        job = self.jobs.get(job_id)
        if not job or not job.control or job.status != "running":
            raise ValueError("this job has no live auto-train controls")
        if action not in CONTROL_ACTIONS:
            raise ValueError(f"unknown control '{action}'")
        with open(job.control, "a", encoding="utf-8") as f:
            f.write(json.dumps({"action": action, "value": value}) + "\n")
        return True

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job.status not in ("queued", "running"):
            return False
        job.status = "cancelled"
        if job.proc and job.proc.poll() is None:
            job.proc.terminate()
            try:
                job.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                job.proc.kill()
        return True

    def list(self):
        return [self.jobs[i].summary() for i in reversed(self.order[-50:])]

    def get(self, job_id, since=0):
        job = self.jobs.get(job_id)
        if not job:
            return None
        with job.lock:
            total = len(job.lines)
            since = max(0, min(int(since), total))
            d = job.summary()
            d["since"] = since
            d["new_lines"] = job.lines[since:]
        return d
