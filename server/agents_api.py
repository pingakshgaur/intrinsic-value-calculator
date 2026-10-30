# FILE: server/agents_api.py
"""
The research workforce in the web app: roster, the agents' messages and live
status (read from the blackboard while a run writes it), and your side of the
conversation.

You can post in any channel or DM an agent; the agents answer, take
instructions and act on commands - see server/agent_chat.py.
"""

import json
import re
import sqlite3
import time

from agents import comms
from server import agent_chat
from agents.blackboard import SCHEMA
from server import data as D

USER = agent_chat.USER
COMMANDS = agent_chat.COMMANDS


def _con():
    p = D.intel_state() / "blackboard.sqlite"
    if not p.exists():
        return None
    con = sqlite3.connect(p, timeout=10)
    con.executescript(SCHEMA)  # an older blackboard gets the new tables
    return con


def _row(r):
    return {"id": r[0], "mid": r[1], "run": r[2], "ts": r[3], "channel": r[4], "sender": r[5], "to": r[6] or None,
            "company": r[7] or None, "kind": r[8], "text": r[9], "data": json.loads(r[10] or "{}"),
            "refs": json.loads(r[11] or "[]")}


COLS = "id, mid, run_id, ts, channel, sender, recipient, company, kind, text, data, refs"


def roster():
    r = comms.roster()
    r["user"] = {"callsign": USER, "title": "You", "team": "USR", "color": "#C9CBCD"}
    r["commands"] = [{"cmd": c, "help": h} for c, h in COMMANDS]
    return r


def runs():
    con = _con()
    if con is None:
        return []
    try:
        rows = con.execute("SELECT r.id, r.started, r.finished, r.mode, r.companies, r.llm_calls, r.note, "
                           "(SELECT COUNT(*) FROM messages m WHERE m.run_id=r.id AND m.channel!='trace') "
                           "FROM runs r ORDER BY r.id DESC LIMIT 60").fetchall()
    finally:
        con.close()
    return [{"id": r[0], "started": r[1], "finished": r[2], "mode": r[3], "companies": r[4], "llm_calls": r[5],
             "note": r[6], "messages": r[7]} for r in rows]


def _latest_run(con):
    r = con.execute("SELECT MAX(id) FROM runs").fetchone()
    return r[0] if r and r[0] else 0


def messages(run=None, channel=None, after=0, before=None, limit=400, company=None, kinds=None, trace=False):
    con = _con()
    if con is None:
        return {"run": None, "messages": []}
    try:
        run = int(run) if run else _latest_run(con)
        q, a = f"SELECT {COLS} FROM messages WHERE (run_id=? OR (run_id=0 AND sender=?))", [run, USER]
        if channel:
            q += " AND channel=?"
            a.append(channel)
        elif not trace:
            q += " AND channel!='trace'"
        if after:
            q += " AND id>?"
            a.append(int(after))
        if before:
            q += " AND id<?"
            a.append(int(before))
        if company:
            q += " AND company=?"
            a.append(company)
        if kinds:
            ks = [k for k in kinds.split(",") if k]
            q += f" AND kind IN ({','.join('?' * len(ks))})"
            a += ks
        q += " ORDER BY id DESC LIMIT ?"
        a.append(max(1, min(int(limit), 12000)))  # a whole run, for the graph's replay
        rows = [_row(r) for r in con.execute(q, a).fetchall()][::-1]
    finally:
        con.close()
    return D.clean({"run": run, "messages": rows})


def channel_stats(run=None):
    con = _con()
    if con is None:
        return {"run": None, "channels": {}}
    try:
        run = int(run) if run else _latest_run(con)
        rows = con.execute("SELECT channel, COUNT(*), MAX(id), MAX(ts) FROM messages WHERE run_id=? OR (run_id=0 AND sender=?) "
                           "GROUP BY channel", (run, USER)).fetchall()
    finally:
        con.close()
    return {"run": run, "channels": {c: {"count": n, "last": last, "ts": ts} for c, n, last, ts in rows}}


def summary(run=None):
    """A run's output in full, however long the run: every company it touched, the
    latest verdict on each, its red flags and its message counts by kind."""
    con = _con()
    if con is None:
        return {"run": None, "companies": [], "verdicts": [], "flags": [], "kinds": {}}
    try:
        run = int(run) if run else _latest_run(con)
        companies = [r[0] for r in con.execute(
            "SELECT DISTINCT company FROM messages WHERE run_id=? AND company IS NOT NULL AND company!='' "
            "AND channel!='trace' ORDER BY company", (run,))]
        # a company can be judged more than once in a run (a review can revise it): the last word counts
        verdicts = [_row(r) for r in con.execute(
            f"SELECT {COLS} FROM messages WHERE id IN (SELECT MAX(id) FROM messages WHERE run_id=? AND kind='verdict' "
            "AND company IS NOT NULL AND company!='' GROUP BY company) ORDER BY id DESC", (run,))]
        flags = [_row(r) for r in con.execute(
            f"SELECT {COLS} FROM messages WHERE run_id=? AND kind='flag' ORDER BY id DESC LIMIT 500", (run,))]
        kinds = dict(con.execute("SELECT kind, COUNT(*) FROM messages WHERE run_id=? AND channel!='trace' GROUP BY kind", (run,)).fetchall())
    finally:
        con.close()
    return D.clean({"run": run, "companies": companies, "verdicts": verdicts, "flags": flags, "kinds": kinds})


def live(after=0, run=None, active_job=None):
    """Everything the graph and the chat need on one poll."""
    con = _con()
    if con is None:
        return {"run": None, "active": False, "progress": None, "status": {}, "messages": [], "last_id": 0}
    try:
        run = int(run) if run else _latest_run(con)
        info = con.execute("SELECT id, started, finished, mode, companies, llm_calls FROM runs WHERE id=?", (run,)).fetchone()
        prog = con.execute("SELECT payload FROM run_progress WHERE run_id=?", (run,)).fetchone()
        status = {a: json.loads(p) for a, p in con.execute("SELECT agent, payload FROM agent_status WHERE run_id=?", (run,))}
        rows = [_row(r) for r in con.execute(f"SELECT {COLS} FROM messages WHERE (run_id=? OR (run_id=0 AND sender=?)) AND id>? "
                                             "ORDER BY id LIMIT 600", (run, USER, int(after or 0))).fetchall()]
        last = con.execute("SELECT MAX(id) FROM messages").fetchone()[0] or 0
    finally:
        con.close()
    active = bool(active_job and active_job.kind == "agents" and info and not info[2])
    # a run started outside the web app (python run.py --agents) has no job here and can be
    # silent for minutes during its base valuation: only a long silence counts as dead
    if info and not info[2] and not active_job and close_interrupted(min_quiet=900):
        return live(after, run, active_job)  # it was a dead run: show it closed
    return D.clean({
        "run": {"id": info[0], "started": info[1], "finished": info[2], "mode": info[3], "companies": info[4],
                "llm_calls": info[5]} if info else None,
        "active": active, "progress": json.loads(prog[0]) if prog else None, "status": status,
        "messages": rows, "last_id": last,
    })


def close_interrupted(min_quiet=120):
    """Runs left open by a research process that died (the server stopped
    mid-run): once silent for `min_quiet` seconds, mark them finished (note
    "interrupted") and their agents idle, so no view shows them still working.
    Only call it while no research job is running. -> count closed"""
    con = _con()
    if con is None:
        return 0
    closed = 0
    try:
        open_runs = [r[0] for r in con.execute("SELECT id FROM runs WHERE finished IS NULL OR finished=''").fetchall()]
        for rid in open_runs:
            last = con.execute("SELECT MAX(ts) FROM messages WHERE run_id=? AND sender!=?", (rid, USER)).fetchone()[0]
            if last and time.time() - last < min_quiet:
                continue  # may still be writing
            closed += 1
            when = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(last)) if last else None
            con.execute("UPDATE runs SET finished=COALESCE(?, started), note=TRIM(COALESCE(note,'') || ' interrupted - the server stopped mid-run') WHERE id=?", (when, rid))
            for agent, payload in con.execute("SELECT agent, payload FROM agent_status WHERE run_id=?", (rid,)).fetchall():
                st = json.loads(payload or "{}")
                if st.get("state") in ("working", "waiting"):
                    st["state"] = "idle"
                    con.execute("UPDATE agent_status SET payload=? WHERE run_id=? AND agent=?", (json.dumps(st), rid, agent))
        con.commit()
    finally:
        con.close()
    return closed


# ---------------------------------------------------------------- your messages
def post(channel, text, jobs=None, wait=False):
    """Store your message now; the agents' replies follow from a background thread
    (or before returning, with wait=True - tests and scripts)."""
    text = (text or "").strip()[:2000]
    if not text:
        raise ValueError("empty message")
    valid = {c["id"] for c in comms.channels()}
    if not (channel in valid or re.fullmatch(r"dm:[A-Z]{3}-\d{2}\|[A-Z]{3}-\d{2}|dm:[A-Z]{3}-\d{2}\|YOU|dm:YOU\|[A-Z]{3}-\d{2}", channel)):
        raise ValueError("unknown channel" if channel != "trace" else "the data-exchange trace is read-only")
    con = _con()
    if con is None:
        raise LookupError("no research run yet - start one with Run research")
    try:
        run = _latest_run(con)
        now = time.time()
        con.execute("INSERT INTO messages (mid, run_id, ts, channel, sender, recipient, company, kind, text, data, refs) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (f"u-{now:.3f}", run, now, channel, USER, "", "", "user", text, "{}", "[]"))
        con.commit()
        history = [_row(r) for r in con.execute(f"SELECT {COLS} FROM messages WHERE channel=? ORDER BY id DESC LIMIT 10", (channel,)).fetchall()][::-1]
    finally:
        con.close()

    def write(replies):
        c = _con()
        if c is None:
            return
        try:
            t = time.time()
            c.executemany("INSERT INTO messages (mid, run_id, ts, channel, sender, recipient, company, kind, text, data, refs) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          [(f"u-{t:.3f}-{i}", run, t + 0.001 * i, channel, sender, USER, company or "", kind, said,
                            agent_chat.dumps(data), json.dumps([f"u-{now:.3f}"])) for i, (sender, said, kind, company, data) in enumerate(replies)])
            c.commit()
        finally:
            c.close()

    pending = [] if text.startswith("/") else agent_chat.targets(text, channel)
    if wait:
        write(agent_chat.answer(text, channel, jobs, history, live))
    else:
        agent_chat.respond_later(text, channel, jobs, history, live, write)
    return {"ok": True, "pending": pending or ["OPS-00"]}


def post_system(text):
    """A message from the orchestrator in #ops (auto-start and the like)."""
    con = _con()
    if con is None:
        return False
    try:
        now = time.time()
        con.execute("INSERT INTO messages (mid, run_id, ts, channel, sender, recipient, company, kind, text, data, refs) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (f"s-{now:.3f}", _latest_run(con), now, "ops", "OPS-00", "", "",
                                                       "system", text, "{}", "[]"))
        con.commit()
    finally:
        con.close()
    return True
