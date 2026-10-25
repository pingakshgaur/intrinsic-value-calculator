"""
The research workforce in the web app: roster, the agents' messages and live
status (read from the blackboard while a run writes it), and your side of the
conversation.

You can post in any channel or DM an agent. Slash-commands are answered by
the agents from the latest research - no LLM call, no API request:

    /help                     what you can ask
    /status                   the current or last run
    /run quick|full [HAL,BEL] start a research run
    /verdict HAL              the chief's verdict
    /flags HAL                red flags, from the validation analyst
    /compare HAL BEL          two verdicts side by side
    /top [n]                  widest gaps to the HYBRID MODEL value
    @EQR-02 HAL  or  /ask EQR-02 HAL   that analyst's latest finding
"""

import json
import re
import sqlite3
import time

from agents import comms
from agents.blackboard import SCHEMA
from server import data as D

USER = "YOU"
COMMANDS = [
    ("/help", "what you can ask"), ("/status", "the current or last run"),
    ("/run quick", "fast news & market sweep (add tickers, and no-llm to skip AI calls: /run quick HAL,BEL no-llm)"), ("/run full", "full research run"),
    ("/verdict HAL", "the chief's verdict"), ("/flags HAL", "red flags"), ("/compare HAL BEL", "two verdicts side by side"),
    ("/top 5", "widest gaps to the HYBRID MODEL value"), ("/ask EQR-02 HAL", "an analyst's latest finding"),
]


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
    return D.clean({
        "run": {"id": info[0], "started": info[1], "finished": info[2], "mode": info[3], "companies": info[4],
                "llm_calls": info[5]} if info else None,
        "active": active, "progress": json.loads(prog[0]) if prog else None, "status": status,
        "messages": rows, "last_id": last,
    })


# ---------------------------------------------------------------- your messages
def _verdicts():
    return D.intel_latest().get("verdicts") or []


def _find(q):
    q = (q or "").strip().strip(",.").upper()
    if not q:
        return None
    vs = _verdicts()
    for v in vs:
        if (v.get("ticker") or "").upper().split(".")[0] == q.split(".")[0]:
            return v
    for v in vs:
        if q.lower() in v["company"].lower():
            return v
    return None


STOP = {"what", "about", "this", "that", "with", "from", "have", "will", "your", "tell", "show", "give", "does",
        "limited", "ltd", "india", "company", "stock", "share", "price", "value", "verdict", "please", "today"}


def _mentioned(text):
    """A covered company named in free text: an exact ticker first, then a
    distinctive word (4+ letters, not filler) inside a company name."""
    words = re.findall(r"[A-Za-z&]{2,}", text)
    vs = _verdicts()
    tick = {(v.get("ticker") or "").upper().split(".")[0]: v for v in vs}
    for w in words:
        if w.upper() in tick:
            return tick[w.upper()]
    for w in words:
        if len(w) >= 4 and w.lower() not in STOP:
            hit = next((v for v in vs if re.search(r"\b" + re.escape(w), v["company"], re.IGNORECASE)), None)
            if hit:
                return hit
    return None


def _fmt_verdict(v):
    return comms.verdict_text(v) + (f" {(v.get('summary') or {}).get('headline', '')}" if (v.get("summary") or {}).get("by") == "llm" else "")


def _answer(text, channel, jobs):
    """-> [(sender, text, kind, company, data)]"""
    t = text.strip()
    m = re.match(r"^@([A-Z]{3}-\d{2})\b\s*(.*)$", t, re.IGNORECASE)
    if m:
        t = f"/ask {m.group(1)} {m.group(2)}"
    dm_with = None
    if channel.startswith("dm:") and USER in channel:
        dm_with = next((p for p in channel[3:].split("|") if p != USER), None)
        if not t.startswith("/") and dm_with:
            t = f"/ask {dm_with} {t}"
    if not t.startswith("/"):
        v = _mentioned(t)
        if v:
            return [("CMD-00", _fmt_verdict(v), "verdict", v["company"], {"label": v.get("label")})]
        return [("OPS-00", "Logged for the team. I answer slash-commands - type /help for the list.", "system", None, {})]

    cmd, *args = t.split()
    cmd = cmd.lower()
    if cmd == "/help":
        return [("OPS-00", "You can ask: " + "  ·  ".join(f"{c} - {h}" for c, h in COMMANDS)
                 + ". Agents answer from the latest research; no LLM call is made.", "system", None, {})]
    if cmd == "/status":
        act = jobs.active() if jobs else None
        st = live(active_job=act)
        p = st.get("progress") or {}
        r = st.get("run") or {}
        if st["active"]:
            msg = f"Run #{r.get('id')} ({r.get('mode')}) in progress: {p.get('done', 0)}/{p.get('total', 0)} companies, {p.get('saved', 0)} requests saved so far."
        elif r:
            msg = f"Idle. Last run #{r.get('id')} ({r.get('mode')}) finished {r.get('finished') or 'n/a'} with {r.get('companies')} companies, {r.get('llm_calls')} LLM calls."
        else:
            msg = "No research run yet. Start one with /run quick or /run full."
        if act and act.kind != "agents":
            msg += f" Another job is running: {act.kind}."
        return [("OPS-00", msg, "system", None, {})]
    if cmd == "/run":
        if not jobs:
            return [("OPS-00", "Runs can only be started from the web app.", "system", None, {})]
        mode = (args[0].lower() if args else "quick")
        if mode not in ("quick", "full"):
            return [("OPS-00", "Use /run quick or /run full, optionally with tickers and no-llm: /run quick HAL,BEL no-llm", "system", None, {})]
        rest = [x for x in args[1:] if x.lower().lstrip("-") not in ("no-llm", "nollm", "rules")]
        no_llm = len(rest) != len(args[1:])
        tickers = ",".join(rest).replace(" ", "")
        try:
            job = jobs.start("agents", {"quick": mode == "quick", "no_llm": no_llm, **({"tickers": tickers} if tickers else {})})
        except (RuntimeError, ValueError) as e:
            return [("OPS-00", f"Couldn't start: {e}", "system", None, {})]
        return [("OPS-00", f"Started a {mode} research run" + (f" on {tickers}" if tickers else "") + (" (rule-based, no LLM calls)" if no_llm else "") + f" (job {job.id}). "
                 "Watch it live on the Agent Network page.", "system", None, {"job": job.id})]
    if cmd in ("/verdict", "/flags", "/ask", "/compare", "/top"):
        if cmd == "/top":
            n = int(args[0]) if args and args[0].isdigit() else 5
            vs = sorted((v for v in _verdicts() if isinstance(v.get("upside"), (int, float))), key=lambda v: -v["upside"])[:max(1, min(n, 15))]
            if not vs:
                return [("CMD-00", "No verdicts yet.", "verdict", None, {})]
            return [("CMD-00", "Widest gaps to the HYBRID MODEL value: " + "; ".join(
                f"{v['company']} {v['upside']:+.0%} ({v.get('label')})" for v in vs) + ".", "verdict", None, {})]
        if cmd == "/compare":
            a, b = (_find(args[0]) if args else None), (_find(args[1]) if len(args) > 1 else None)
            if not a or not b:
                return [("CMD-00", "Name two covered companies: /compare HAL BEL", "verdict", None, {})]
            return [("CMD-00", f"{_fmt_verdict(a)}  |  {_fmt_verdict(b)}", "verdict", None, {})]
        if cmd == "/ask":
            cs = (args[0].upper() if args else "")
            if cs not in comms.ROSTER:
                return [("OPS-00", "Name an agent by callsign, e.g. /ask EQR-02 HAL (see the Agents list).", "system", None, {})]
            v = _find(" ".join(args[1:])) if len(args) > 1 else None
            agent = comms.ROSTER[cs]
            if not v:
                return [(cs, f"{agent['title']} here. {agent['duty']} Name a covered company and I'll give you my latest read.",
                         "reply", None, {})]
            if agent["role"] == "lead":
                rep = next((r for r in v.get("leads") or [] if comms.BY_KEY.get(r.get("lead")) == cs), None)
                if rep:
                    return [(cs, comms.summary_text(rep, v["company"]), "summary", v["company"], {"score": rep.get("score")})]
            if agent["role"] == "chief":
                return [(cs, _fmt_verdict(v), "verdict", v["company"], {})]
            a = next((a for a in v.get("analysts") or [] if comms.BY_KEY.get(a.get("agent")) == cs), None)
            if not a:
                return [(cs, f"I have no finding on {v['company']} in the latest run.", "reply", v["company"], {})]
            txt = (f"{v['company']}: score {a.get('score', 0):+.2f}, confidence {a.get('confidence', 0):.0%}"
                   + ("" if a.get("validated") is not False else " (excluded by validation)") + f". {a.get('summary', '')[:400]}")
            return [(cs, txt, "finding", v["company"], {"score": a.get("score"), "confidence": a.get("confidence"),
                                                        "evidence": a.get("evidence", [])[:4]})]
        v = _find(" ".join(args))
        if not v:
            return [("CMD-00", "I don't cover that company. Try a ticker like HAL.", "verdict", None, {})]
        if cmd == "/verdict":
            return [("CMD-00", _fmt_verdict(v), "verdict", v["company"], {"label": v.get("label")})]
        flags = v.get("red_flags") or []
        return [("IRV-01", f"{v['company']}: " + ("; ".join(flags[:6]) if flags else "no validated red flags."), "flag" if flags else "review",
                 v["company"], {"flags": flags[:6]})]
    return [("OPS-00", f"Unknown command {cmd}. Type /help.", "system", None, {})]


def post(channel, text, jobs=None):
    text = (text or "").strip()[:2000]
    if not text:
        raise ValueError("empty message")
    valid = {c["id"] for c in comms.channels()} | {"trace"}
    if not (channel in valid or re.fullmatch(r"dm:[A-Z]{3}-\d{2}\|[A-Z]{3}-\d{2}|dm:[A-Z]{3}-\d{2}\|YOU|dm:YOU\|[A-Z]{3}-\d{2}", channel)):
        raise ValueError("unknown channel")
    con = _con()
    if con is None:
        raise LookupError("no research run yet - start one with Run research")
    replies = _answer(text, channel, jobs)
    try:
        run = _latest_run(con)
        now = time.time()
        rows = [(f"u-{now:.3f}", run, now, channel, USER, "", None, "user", text, "{}", "[]")]
        for i, (sender, t, kind, company, data) in enumerate(replies):
            rows.append((f"u-{now:.3f}-{i}", run, now + 0.001 * (i + 1), channel, sender, USER, company or "", kind, t,
                         json.dumps(data, default=str), "[]"))
        con.executemany("INSERT INTO messages (mid, run_id, ts, channel, sender, recipient, company, kind, text, data, refs) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)", [(r[0], r[1], r[2], r[3], r[4], r[5], r[6] or "", r[7], r[8], r[9], r[10]) for r in rows])
        con.commit()
    finally:
        con.close()
    return {"ok": True, "replies": len(replies)}


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
