"""
The research workforce starts working as soon as the web app starts.

A few seconds after `python run.py --web` comes up, a research run is started
(a quick sweep by default) unless another job is already running. Set
`skip_recent` to skip it when a run finished within that many minutes. By default it runs rule-based, so
a restart never spends the free LLM quotas; switch `llm` on to let it use
them. Settings live in data/live/autostart.json and on the Agent Network page.
"""

import datetime as dt
import logging
import threading
import time

from server import agents_api
from server.live import LIVE, _read_json, _write_json

log = logging.getLogger("web.autostart")
SETTINGS = LIVE / "autostart.json"
DEFAULTS = {"enabled": True, "mode": "quick", "llm": False, "skip_recent": 0}
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


def start_now(jobs, why="startup"):
    """Start the configured run unless something else is running. -> (job or None, reason)"""
    s = settings()
    if jobs.active():
        return None, "another job is running"
    job = jobs.start("agents", {"quick": s["mode"] == "quick", "no_llm": not s["llm"], "auto": why})
    agents_api.post_system(f"Research workforce started on {why}: {s['mode']} run"
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
