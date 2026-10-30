# FILE: server/autostart.py
"""
The research workforce starts working as soon as the web app starts.

A few seconds after `python run.py --web` comes up, a research run is started
(a quick sweep by default) unless another job is already running. Set
`skip_recent` to skip it when a run finished within that many minutes. By default it runs rule-based, so
a restart never spends the free LLM quotas; switch `llm` on to let it use
them. Settings live in data/live/autostart.json and on the Agent Network page.

It only ever researches the companies on the watchlists: the ones picked in
`watchlists`, or every watchlist when none are picked. With no companies on any
of them there is nothing to research and the run is skipped.
"""

import datetime as dt
import logging
import threading
import time

from server import agents_api, live
from server.live import LIVE, _read_json, _write_json

log = logging.getLogger("web.autostart")
SETTINGS = LIVE / "autostart.json"
DEFAULTS = {"enabled": True, "mode": "quick", "llm": False, "skip_recent": 0, "watchlists": []}
state = {"last": None, "reason": None}


def settings():
    s = dict(DEFAULTS)
    s.update({k: v for k, v in _read_json(SETTINGS, {}).items() if k in DEFAULTS})
    return s


def save(patch):
    s = settings()
    if "enabled" in patch:
        s["enabled"] = bool(patch["enabled"])
    if "llm" in patch:
        s["llm"] = bool(patch["llm"])
    if patch.get("mode") in ("quick", "full"):
        s["mode"] = patch["mode"]
    if "skip_recent" in patch:
        try:
            s["skip_recent"] = max(0, min(1440, int(patch["skip_recent"])))
        except (TypeError, ValueError):
            raise ValueError("skip_recent must be a number of minutes")
    if "watchlists" in patch:
        ids = patch["watchlists"] or []
        if not isinstance(ids, list):
            raise ValueError("watchlists must be a list of watchlist ids")
        known = {x["id"] for x in live.watchlists()["lists"]}
        s["watchlists"] = [str(i) for i in dict.fromkeys(ids) if str(i) in known]
    _write_json(SETTINGS, s)
    return s


def _minutes_since_last_run():
    runs = agents_api.runs()
    if not runs or not runs[0].get("finished"):
        return None
    try:
        return (dt.datetime.now() - dt.datetime.fromisoformat(runs[0]["finished"])).total_seconds() / 60
    except ValueError:
        return None


def target_lists(s=None):
    """Ids of the watchlists an automatic run researches: the picked ones that still
    exist and have companies, or every watchlist with companies when none are picked."""
    s = s or settings()
    lists = [x for x in live.watchlists()["lists"] if x.get("tickers")]
    picked = set(s["watchlists"])
    return [x["id"] for x in lists if not picked or x["id"] in picked]


def start_now(jobs, why="startup"):
    """Start the configured run unless something else is running. -> (job or None, reason)"""
    s = settings()
    if jobs.active():
        return None, "another job is running"
    ids = target_lists(s)
    if not ids:
        return None, "skipped: no companies on the chosen watchlists"
    job = jobs.start("agents", {"quick": s["mode"] == "quick", "no_llm": not s["llm"], "auto": why, "watchlist": ids})
    agents_api.post_system(f"Research workforce started on {why}: {s['mode']} run on "
                           + (job.opts.get("watchlist_name") or "the watchlists")
                           + ("" if s["llm"] else ", rule-based (no LLM calls)") + f" - job {job.id}.")
    return job, "started"


def _on_startup(jobs):
    time.sleep(4)  # let the server settle first
    s = settings()
    try:
        if not s["enabled"]:
            state.update(last=time.time(), reason="auto-start is off")
            return
        ago = _minutes_since_last_run()
        if ago is not None and ago < s["skip_recent"]:
            state.update(last=time.time(), reason=f"skipped: the last run finished {ago:.0f} min ago")
            return
        job, reason = start_now(jobs)
        state.update(last=time.time(), reason=reason if job is None else f"started job {job.id}")
    except Exception as e:
        log.exception("research auto-start failed")
        state.update(last=time.time(), reason=f"failed: {type(e).__name__}: {e}")


def schedule(jobs):
    threading.Thread(target=_on_startup, args=(jobs,), daemon=True, name="autostart").start()
