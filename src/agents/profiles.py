"""
Per-agent tuning, set from the web app (Agents -> an agent -> Settings) or by
talking to the agent in the Research Room.

Each agent has a profile; anything not set falls back to the default below,
so an empty or missing file changes nothing:

    enabled         false skips the analyst in research runs (leads, the
                    chief and the orchestrator always run)
    weight          x its weight in the lead's team report (0 - 3)
    llm             auto | fast | smart | off - which model tier its LLM
                    calls use, or none at all (rule-based path only)
    stance          cautious | balanced | bold - shrinks or stretches the
                    scores it reports
    min_confidence  findings below this confidence are reported but ignored
    rerun_quick     true re-runs a slow analyst in quick sweeps instead of
                    re-using its finding from the last full run
    instructions    your standing instructions; added to every LLM prompt the
                    agent sends and to its persona when it answers you

Stored next to the blackboard in the state directory (agent_profiles.json).
"""

import json
import logging
import threading

from agents import settings as S

log = logging.getLogger("agents.profiles")

DEFAULT = {"enabled": True, "weight": 1.0, "llm": "auto", "stance": "balanced", "min_confidence": 0.0,
           "rerun_quick": False, "instructions": ""}
LLM_MODES = ("auto", "fast", "smart", "off")
STANCES = {"cautious": 0.75, "balanced": 1.0, "bold": 1.25}
MAX_INSTRUCTIONS = 1500

_lock = threading.Lock()
_cache = {"mtime": None, "data": {}}


def _file():
    return S.state_dir() / "agent_profiles.json"


def _read():
    p = _file()
    try:
        m = p.stat().st_mtime
    except OSError:
        return {}
    if _cache["mtime"] != m:
        try:
            _cache["data"] = json.loads(p.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError) as e:
            log.error("agent profiles unreadable (%s) - defaults used", e)
            _cache["data"] = {}
        _cache["mtime"] = m
    return _cache["data"]


def clean(patch):
    """Validate one profile patch. -> dict of accepted fields. Raises ValueError."""
    out = {}
    for k, v in (patch or {}).items():
        if k not in DEFAULT:
            raise ValueError(f"unknown setting {k}")
        if k in ("enabled", "rerun_quick"):
            out[k] = bool(v)
        elif k == "weight":
            out[k] = round(min(3.0, max(0.0, float(v))), 3)
        elif k == "min_confidence":
            out[k] = round(min(1.0, max(0.0, float(v))), 3)
        elif k == "llm":
            if v not in LLM_MODES:
                raise ValueError(f"llm must be one of {', '.join(LLM_MODES)}")
            out[k] = v
        elif k == "stance":
            if v not in STANCES:
                raise ValueError(f"stance must be one of {', '.join(STANCES)}")
            out[k] = v
        elif k == "instructions":
            out[k] = str(v or "").strip()[:MAX_INSTRUCTIONS]
    return out


def get(callsign):
    """The full profile for one callsign (defaults filled in)."""
    return {**DEFAULT, **(_read().get(callsign) or {})}


def all_profiles(callsigns):
    data = _read()
    return {cs: {**DEFAULT, **(data.get(cs) or {})} for cs in callsigns}


def save(callsign, patch):
    """Merge a patch into one agent's profile. -> the new full profile."""
    ok = clean(patch)
    with _lock:
        data = dict(_read())
        cur = {**(data.get(callsign) or {}), **ok}
        # store only what differs from the default, so the file stays readable
        cur = {k: v for k, v in cur.items() if DEFAULT.get(k) != v}
        if cur:
            data[callsign] = cur
        else:
            data.pop(callsign, None)
        p = _file()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
        _cache["mtime"] = None
    return get(callsign)


def reset(callsign=None):
    """Back to defaults: one agent, or everyone."""
    with _lock:
        data = {} if callsign is None else {k: v for k, v in _read().items() if k != callsign}
        p = _file()
        p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        _cache["mtime"] = None


def add_instruction(callsign, text):
    """Append one standing instruction (newest last, oldest dropped past the limit)."""
    cur = get(callsign)["instructions"]
    lines = [x for x in cur.splitlines() if x.strip()] + [text.strip()]
    while len("\n".join(lines)) > MAX_INSTRUCTIONS and len(lines) > 1:
        lines.pop(0)
    return save(callsign, {"instructions": "\n".join(lines)})


# ----------------------------------------------------------- used in runs
def by_key(key):
    """Profile for an agent class KEY (the runner knows keys, the web app callsigns)."""
    from agents import comms

    cs = comms.BY_KEY.get(key)
    return get(cs) if cs else dict(DEFAULT)


def weight(key):
    p = by_key(key)
    return 0.0 if not p["enabled"] else float(p["weight"])


def apply(finding):
    """A finished finding, adjusted for its agent's stance and confidence floor."""
    p = by_key(finding.agent)
    k = STANCES.get(p["stance"], 1.0)
    if k != 1.0 and finding.score:
        finding.score = max(-1.0, min(1.0, finding.score * k))
        finding.notes.append(f"stance {p['stance']} (x{k:g})")
    if p["min_confidence"] and finding.status == "ok" and finding.confidence < p["min_confidence"]:
        # the lead leaves it out of the team report (see chief.lead_report)
        finding.notes.append(f"confidence {finding.confidence:.0%} below this agent's floor {p['min_confidence']:.0%} - ignored")
    return finding


def below_floor(finding):
    return finding.confidence < by_key(finding.agent)["min_confidence"]


def llm_tier(key, tier):
    """-> the tier to use, or None when this agent is told not to use an LLM."""
    mode = by_key(key)["llm"]
    if mode == "off":
        return None
    return tier if mode == "auto" else mode


def instructions_for(key=None, callsign=None):
    p = get(callsign) if callsign else by_key(key)
    t = p["instructions"].strip()
    return f"\n\nStanding instructions from the portfolio manager (follow them unless they conflict with the evidence rules):\n{t}" if t else ""
