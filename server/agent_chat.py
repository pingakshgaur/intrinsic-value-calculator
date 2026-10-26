"""
Your side of the Research Room: the agents answer you, take instructions and
act on commands.

Who answers: the agent you DM, the agents you @mention (up to three), or the
channel's lead (#command -> the chief, #ops -> the orchestrator).

What they do with a message:

    an instruction   "from now on focus on debt", "be more cautious",
                     "ignore promoter pledges" - kept in the agent's profile
                     and used from the next run (stance changes apply directly)
    a request        "re-check HAL", "look into Bharat Electronics" - starts a
                     quick research run on that company
    stop / resume    "sit out the next runs" / "you're back" (analysts only)
    a question       answered in character: with an LLM when one is set up
                     (grounded in the agent's latest research, never invented
                     figures), otherwise from its latest findings

Slash-commands are the precise form of the same things (see COMMANDS).
Replies are written by a background thread, so posting returns at once; the
web app shows "<agent> is typing" until the reply lands.
"""

import json
import logging
import re
import threading
import time

from agents import comms, profiles
from server import data as D

log = logging.getLogger("server.agent_chat")

USER = "YOU"
COMMANDS = [
    ("/help", "what you can ask"), ("/status", "the current or last run"),
    ("/run quick", "fast news & market sweep (add tickers, and no-llm to skip AI calls: /run quick HAL,BEL no-llm)"),
    ("/run full", "full research run"), ("/recheck HAL", "quick research run on one company"),
    ("/verdict HAL", "the chief's verdict"), ("/flags HAL", "red flags"), ("/compare HAL BEL", "two verdicts side by side"),
    ("/top 5", "widest gaps to the HYBRID MODEL value"), ("/ask EQR-02 HAL", "an analyst's latest finding"),
    ("/instruct EQR-02 focus on debt", "a standing instruction for an agent"),
    ("/profile EQR-02", "an agent's settings and instructions"), ("/forget EQR-02", "clear its instructions"),
    ("/disable EQR-02", "leave an analyst out of runs"), ("/enable EQR-02", "bring it back"),
    ("/weight EQR-02 1.5", "its weight in the team report (0-3)"),
    ("/stance EQR-02 cautious", "cautious, balanced or bold"), ("/llm EQR-02 off", "auto, fast, smart or off"),
]

# --------------------------------------------------------------- research lookups
STOP = {"what", "about", "this", "that", "with", "from", "have", "will", "your", "tell", "show", "give", "does",
        "limited", "ltd", "india", "company", "stock", "share", "price", "value", "verdict", "please", "today",
        "more", "less", "focus", "always", "never", "check", "look", "into", "research", "think", "should"}


def _verdicts():
    return D.intel_latest().get("verdicts") or []


def _find(q):
    q = (q or "").strip().strip(",.?!").upper()
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


def _mentioned(text):
    """A covered company named in free text: an exact ticker first, then a
    distinctive word (4+ letters, not filler) inside a company name."""
    words = re.findall(r"[A-Za-z&]{2,}", text)
    vs = _verdicts()
    tick = {(v.get("ticker") or "").upper().split(".")[0]: v for v in vs}
    for w in words:
        if w.isupper() and w in tick:
            return tick[w]
    for w in words:
        if w.upper() in tick and len(w) >= 3:
            return tick[w.upper()]
    for w in words:
        if len(w) >= 4 and w.lower() not in STOP:
            hit = next((v for v in vs if re.search(r"\b" + re.escape(w), v["company"], re.IGNORECASE)), None)
            if hit:
                return hit
    return None


def _fmt_verdict(v):
    return comms.verdict_text(v) + (f" {(v.get('summary') or {}).get('headline', '')}" if (v.get("summary") or {}).get("by") == "llm" else "")


def _finding(cs, v):
    """-> (text, kind, data): this agent's latest read on one company."""
    agent = comms.ROSTER[cs]
    if agent["role"] == "chief":
        return _fmt_verdict(v), "verdict", {"label": v.get("label")}
    if agent["role"] == "lead":
        rep = next((r for r in v.get("leads") or [] if comms.BY_KEY.get(r.get("lead")) == cs), None)
        if rep:
            return comms.summary_text(rep, v["company"]), "summary", {"score": rep.get("score"), "confidence": rep.get("confidence")}
        return f"I have no team report on {v['company']} in the latest run.", "reply", {}
    a = next((a for a in v.get("analysts") or [] if comms.BY_KEY.get(a.get("agent")) == cs), None)
    if not a:
        return f"I have no finding on {v['company']} in the latest run.", "reply", {}
    txt = (f"{v['company']}: score {a.get('score', 0):+.2f}, confidence {a.get('confidence', 0):.0%}"
           + ("" if a.get("validated") is not False else " (excluded by validation)") + f". {a.get('summary', '')[:400]}")
    return txt, "finding", {"score": a.get("score"), "confidence": a.get("confidence"), "evidence": a.get("evidence", [])[:4]}


# --------------------------------------------------------------- the LLM voice
_router = {"r": None, "at": 0.0}


def _llm():
    """One router for the chat, rebuilt every 10 minutes so new keys are picked up."""
    if _router["r"] is None or time.time() - _router["at"] > 600:
        from agents import settings as S
        from agents.llm import LLMRouter

        S.load_dotenv()
        _router["r"] = LLMRouter(None, enabled=True)
        _router["at"] = time.time()
    return _router["r"] if _router["r"].enabled else None


def _persona(cs):
    a = comms.ROSTER[cs]
    team = comms.TEAMS[a["team"]]
    p = profiles.get(cs)
    inputs = ", ".join(comms.SOURCES[s]["title"] for s in comms.INPUTS.get(cs, []) if s in comms.SOURCES) or "the other agents' work"
    return (f"You are {cs}, the {a['title']} in the {team['name']} team of an equity research workforce covering Indian listed companies. "
            f"Your job: {a['duty']} You work from: {inputs}. "
            f"Your current settings: stance {p['stance']}, weight x{p['weight']:g}, {'switched off' if not p['enabled'] else 'active'}, LLM {p['llm']}."
            + profiles.instructions_for(callsign=cs))


def _llm_reply(cs, text, v, history):
    r = _llm()
    if r is None or profiles.get(cs)["llm"] == "off":
        return None
    ctx = ""
    if v:
        t, _, _ = _finding(cs, v)
        ctx = (f"\n\nYour latest research on {v['company']}: {t}\nThe chief's verdict: {_fmt_verdict(v)}"
               + (f"\nRed flags: {'; '.join((v.get('red_flags') or [])[:5])}" if v.get("red_flags") else ""))
    convo = "\n".join(f"{m['sender']}: {m['text'][:300]}" for m in history[-8:])
    system = (_persona(cs) + "\n\nYou are chatting with the portfolio manager (YOU) in the Research Room. Reply in first person, "
              "plainly and briefly (at most 120 words). Ground every figure in the research given below; if you do not have it, "
              "say so and say what you would need - never invent numbers, prices or news. If you are asked to do something you "
              "cannot do from chat, say which command would do it (for example /recheck HAL).")
    user = (f"Recent conversation:\n{convo}\n" if convo else "") + ctx + f"\n\nThe portfolio manager says: {text}"
    tier = profiles.llm_tier(comms.ROSTER[cs]["key"], "smart") or "smart"
    out = r.complete(tier, system, user, max_tokens=400, json_mode=False, agent=f"chat:{cs}")
    return out.strip() if isinstance(out, str) and out.strip() else None


# --------------------------------------------------------------- intents
INSTRUCT = re.compile(r"^(please\s+)?(from now on|going forward|in future|always|never|make sure|remember|keep in mind|"
                      r"focus (more )?on|prioriti[sz]e|pay (more |closer )?attention|ignore|don'?t|do not|stop using|watch (out )?for|"
                      r"be (more|less) )", re.IGNORECASE)
# only unambiguous verbs start work: "update me on HAL" or "review HAL" are questions, not run requests
ACT = re.compile(r"^(please\s+|can you\s+|could you\s+)?(re-?check|re-?research|research|re-?analy[sz]e|analy[sz]e|"
                 r"look into|investigate|dig into|re-?run)\b", re.IGNORECASE)
CAUTIOUS = re.compile(r"\b(more|be) (cautious|conservative|careful|sceptical|skeptical)\b|\bless (aggressive|bold|optimistic)\b", re.IGNORECASE)
BOLD = re.compile(r"\b(more|be) (aggressive|bold|optimistic)\b|\bless (cautious|conservative)\b", re.IGNORECASE)
NEUTRAL = re.compile(r"\b(balanced|neutral|normal) (stance|again)\b|\bback to (balanced|normal)\b", re.IGNORECASE)
PAUSE = re.compile(r"\b(sit out|take a break|stand down|pause|stop working|switch off|turn off)\b", re.IGNORECASE)
RESUME = re.compile(r"\b(you'?re back|come back|resume|start (working )?again|switch on|turn on|back to work)\b", re.IGNORECASE)


def _start_run(jobs, v, who):
    if not jobs:
        return "I can't start research from here - use Run research in the web app."
    tick = (v.get("ticker") or "").split(".")[0]
    try:
        job = jobs.start("agents", {"quick": True, "tickers": tick})
    except (RuntimeError, ValueError) as e:
        return f"I couldn't start that: {e}"
    return f"On it - started a quick research run on {v['company']} (job {job.id}). Our reports land in the team channels as we finish."


def _profile_text(cs):
    p = profiles.get(cs)
    ins = p["instructions"].strip()
    return (f"{cs} settings: {'active' if p['enabled'] else 'switched off'} · weight x{p['weight']:g} · stance {p['stance']} · "
            f"LLM {p['llm']} · confidence floor {p['min_confidence']:.0%} · "
            f"{'re-runs' if p['rerun_quick'] else 're-uses its last finding'} in quick sweeps. "
            + (f"Standing instructions: {ins.replace(chr(10), ' / ')}" if ins else "No standing instructions."))


def _talk(cs, text, jobs, history):
    """One agent's answer to a free-text message. -> (text, kind, company, data)"""
    a = comms.ROSTER[cs]
    v = _mentioned(text)
    company = v["company"] if v else None
    analyst = a["role"] == "analyst"
    if a["role"] == "system":
        if ACT.match(text) and v:
            return _start_run(jobs, v, cs), "system", company, {}
        return ("I run the jobs and keep time; ask a team lead or the chief about research. "
                "I can start runs: say 're-check HAL' or use /run quick."), "system", None, {}

    if ACT.match(text) and v:
        return _start_run(jobs, v, cs), "reply", company, {"action": "run"}
    if NEUTRAL.search(text):
        profiles.save(cs, {"stance": "balanced"})
        return "Understood - back to a balanced stance from the next run.", "reply", None, {"profile": "stance"}
    if CAUTIOUS.search(text):
        profiles.save(cs, {"stance": "cautious"})
        return ("Understood - I'll take a cautious stance: my scores are scaled down by a quarter from the next run. "
                "Say 'back to balanced' to undo."), "reply", None, {"profile": "stance"}
    if BOLD.search(text):
        profiles.save(cs, {"stance": "bold"})
        return ("Understood - I'll take a bolder stance: my scores are stretched by a quarter from the next run. "
                "Say 'back to balanced' to undo."), "reply", None, {"profile": "stance"}
    if analyst and PAUSE.search(text):
        profiles.save(cs, {"enabled": False})
        return "Okay - I'll sit out the research runs until you say I'm back. My team lead weighs the others without me.", "reply", None, {"profile": "enabled"}
    if analyst and RESUME.search(text):
        profiles.save(cs, {"enabled": True})
        return "Back on the team - I'll take part from the next run.", "reply", None, {"profile": "enabled"}
    if INSTRUCT.match(text) and not text.rstrip().endswith("?"):  # "don't you think...?" is a question
        profiles.add_instruction(cs, text)
        llm_note = "" if profiles.get(cs)["llm"] != "off" else " (my LLM is off, so switch it on for this to shape my analysis)"
        return (f"Noted - I'll keep that as a standing instruction from the next run{llm_note}. "
                f"/profile {cs} shows them all, /forget {cs} clears them."), "reply", None, {"profile": "instructions"}

    said = _llm_reply(cs, text, v, history)
    if said:
        return said, "reply", company, {"llm": True}
    if v:
        t, kind, data = _finding(cs, v)
        return t, kind, company, data
    p = profiles.get(cs)
    return (f"{a['title']} here. {a['duty']} Name a covered company and I'll give you my latest read; "
            f"tell me how to work (e.g. 'focus on debt levels', 'be more cautious') and I'll keep it for the next run."
            + ("" if p["enabled"] else " I'm switched off at the moment - say 'you're back' to bring me in.")), "reply", None, {}


# --------------------------------------------------------------- slash-commands
def _command(t, channel, jobs, live_fn):
    """-> [(sender, text, kind, company, data)]"""
    cmd, *args = t.split()
    cmd = cmd.lower()
    if cmd == "/help":
        return [("OPS-00", "You can ask: " + "  ·  ".join(f"{c} - {h}" for c, h in COMMANDS)
                 + ". Or just talk to an agent: DM it or @mention it, ask a question, give it an instruction "
                   "('focus on debt', 'be more cautious') or a task ('re-check HAL').", "system", None, {})]
    if cmd == "/status":
        act = jobs.active() if jobs else None
        st = live_fn(active_job=act)
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
    if cmd == "/recheck":
        v = _find(" ".join(args))
        if not v:
            return [("OPS-00", "Name a covered company: /recheck HAL", "system", None, {})]
        return [("OPS-00", _start_run(jobs, v, "OPS-00"), "system", v["company"], {})]
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

    # commands about one agent
    if cmd in ("/instruct", "/profile", "/forget", "/enable", "/disable", "/weight", "/stance", "/llm"):
        cs = (args[0].upper().lstrip("@") if args else "")
        if cs not in comms.ROSTER or comms.ROSTER[cs]["role"] == "system":
            return [("OPS-00", f"Name an agent by callsign, e.g. {cmd} EQR-02.", "system", None, {})]
        rest = " ".join(args[1:]).strip()
        analyst = comms.ROSTER[cs]["role"] == "analyst"
        try:
            if cmd == "/profile":
                return [(cs, _profile_text(cs), "reply", None, {"profile": True})]
            if cmd == "/instruct":
                if not rest:
                    return [(cs, "Tell me what to do: /instruct " + cs + " focus on debt levels", "reply", None, {})]
                profiles.add_instruction(cs, rest)
                return [(cs, f"Noted - standing instruction kept: \"{rest[:200]}\". It shapes my work from the next run.", "reply", None, {"profile": "instructions"})]
            if cmd == "/forget":
                profiles.save(cs, {"instructions": ""})
                return [(cs, "Cleared - no standing instructions now.", "reply", None, {"profile": "instructions"})]
            if cmd in ("/enable", "/disable"):
                if not analyst:
                    return [(cs, "Leads and the chief always take part - you can only switch analysts on and off.", "reply", None, {})]
                profiles.save(cs, {"enabled": cmd == "/enable"})
                return [(cs, "Back on the team from the next run." if cmd == "/enable" else "Switched off - I'll sit out runs until /enable.", "reply", None, {"profile": "enabled"})]
            if cmd == "/weight":
                p = profiles.save(cs, {"weight": float(rest)})
                return [(cs, f"My weight in the team report is now x{p['weight']:g}.", "reply", None, {"profile": "weight"})]
            if cmd == "/stance":
                p = profiles.save(cs, {"stance": rest.lower()})
                return [(cs, f"Stance set to {p['stance']} from the next run.", "reply", None, {"profile": "stance"})]
            if cmd == "/llm":
                p = profiles.save(cs, {"llm": rest.lower()})
                return [(cs, f"LLM set to {p['llm']}.", "reply", None, {"profile": "llm"})]
        except ValueError as e:
            return [(cs, f"That didn't work: {e}.", "reply", None, {})]

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
            cs = (args[0].upper().lstrip("@") if args else "")
            if cs not in comms.ROSTER or comms.ROSTER[cs]["role"] == "system":
                return [("OPS-00", "Name an agent by callsign, e.g. /ask EQR-02 HAL (see the Agents list).", "system", None, {})]
            v = _find(" ".join(args[1:])) if len(args) > 1 else None
            if not v:
                agent = comms.ROSTER[cs]
                return [(cs, f"{agent['title']} here. {agent['duty']} Name a covered company and I'll give you my latest read.", "reply", None, {})]
            t, kind, data = _finding(cs, v)
            return [(cs, t, kind, v["company"], data)]
        v = _find(" ".join(args))
        if not v:
            return [("CMD-00", "I don't cover that company. Try a ticker like HAL.", "verdict", None, {})]
        if cmd == "/verdict":
            return [("CMD-00", _fmt_verdict(v), "verdict", v["company"], {"label": v.get("label")})]
        flags = v.get("red_flags") or []
        return [("IRV-01", f"{v['company']}: " + ("; ".join(flags[:6]) if flags else "no validated red flags."), "flag" if flags else "review",
                 v["company"], {"flags": flags[:6]})]
    return [("OPS-00", f"Unknown command {cmd}. Type /help.", "system", None, {})]


# --------------------------------------------------------------- routing
def targets(text, channel):
    """Which agents answer a free-text message."""
    found = [m.upper() for m in re.findall(r"@([A-Za-z]{3}-\d{2})\b", text)]
    named = [cs for cs in dict.fromkeys(found) if cs in comms.ROSTER][:3]
    if named:
        return named
    if channel.startswith("dm:"):
        peer = next((p for p in channel[3:].split("|") if p != USER), None)
        return [peer] if peer in comms.ROSTER else []
    ch = next((c for c in comms.channels() if c["id"] == channel), None)
    if ch:
        return [comms.LEAD_OF.get(ch["team"], "OPS-00") if ch["team"] != "OPS" else "OPS-00"]
    return ["OPS-00"]


def answer(text, channel, jobs, history, live_fn):
    """-> [(sender, text, kind, company, data)] for one message of yours."""
    t = text.strip()
    if t.startswith("/"):
        return _command(t, channel, jobs, live_fn)
    body = re.sub(r"@[A-Za-z]{3}-\d{2}\b[:,]?\s*", "", t).strip() or t
    out = []
    for cs in targets(t, channel):
        try:
            said, kind, company, data = _talk(cs, body, jobs, history)
        except Exception as e:  # one agent's bad answer never drops the others
            log.exception("%s could not answer", cs)
            said, kind, company, data = f"Sorry - I hit an error answering that ({type(e).__name__}).", "reply", None, {}
        out.append((cs, said, kind, company, data))
    return out


def respond_later(text, channel, jobs, history, live_fn, write):
    """Answer on a background thread; `write(replies)` stores them."""
    def go():
        try:
            replies = answer(text, channel, jobs, history, live_fn)
        except Exception:
            log.exception("chat answer failed")
            replies = [("OPS-00", "Something went wrong answering that - try again, or /help.", "system", None, {})]
        try:
            write(replies)
        except Exception:
            log.exception("chat reply could not be stored")

    threading.Thread(target=go, name="agent-chat", daemon=True).start()


def dumps(data):
    return json.dumps(data, default=str)
