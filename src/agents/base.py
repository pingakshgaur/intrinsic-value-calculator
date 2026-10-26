"""
The vocabulary every agent speaks: Evidence, Finding, Agent.

EVIDENCE FIRST

An agent may only claim what it can point at. Each Evidence item carries its
source, a URL where one exists, and the date the underlying fact refers to.
The Research Validation analyst later rejects findings whose evidence is
missing, stale, or unsourced - and an LLM-written claim that cites an
evidence id that does not exist is dropped, not trusted.

SCORES

    score       -1 .. +1   bad for the stock's value .. good for it
    risk         0 .. 1    optional, for agents that feed a discount-rate premium
    confidence   0 .. 1    how much the agent trusts its own reading

Everything an agent wants the formula to use goes in `signals`, a flat dict
of named numbers (for example {"pledge_pct": 0.31}). The formula reads
signals by name, so the link from agent to rupee value stays traceable.
"""

import datetime as dt
import hashlib
import logging
import time
import traceback
from dataclasses import dataclass, field, asdict
from typing import Optional

log = logging.getLogger("agents")


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def today():
    return dt.date.today()


@dataclass
class Evidence:
    source: str  # "yfinance", "NSE announcements", "Economic Times", ...
    title: str
    url: str = ""
    date: str = ""  # ISO date the fact refers to
    value: Optional[float] = None
    kind: str = "data"  # data | news | filing | macro | derived
    credibility: float = 1.0
    id: str = ""

    def __post_init__(self):
        if not self.id:
            raw = f"{self.source}|{self.title}|{self.url}|{self.date}"
            self.id = "E" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]

    def age_days(self):
        try:
            return (today() - dt.date.fromisoformat(self.date[:10])).days
        except (ValueError, TypeError):
            return None


@dataclass
class Finding:
    agent: str
    lead: str
    company: str
    score: float = 0.0
    confidence: float = 0.0
    summary: str = ""
    signals: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    flags: list = field(default_factory=list)  # red flags, plain sentences
    notes: list = field(default_factory=list)
    used_llm: bool = False
    status: str = "ok"  # ok | no_data | error
    validated: Optional[bool] = None
    seconds: float = 0.0

    @property
    def has_evidence(self):
        return bool(self.evidence) and self.status == "ok"

    def to_dict(self):
        d = asdict(self)
        d["evidence"] = [asdict(e) if isinstance(e, Evidence) else e for e in self.evidence]
        return d

    @classmethod
    def from_dict(cls, d):
        """Rebuild a stored finding (quick runs reuse slow-moving ones)."""
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        ev = []
        for e in known.get("evidence", []) or []:
            if isinstance(e, dict):
                ev.append(Evidence(**{k: v for k, v in e.items() if k in Evidence.__dataclass_fields__}))
        known["evidence"] = ev
        known["validated"] = None
        return cls(**known)


class Agent:
    """
    One analyst. Subclasses set KEY, NAME, LEAD, ROLE and implement analyse().

    run() wraps analyse() so a crash, a dead website or an exhausted LLM quota
    turns into a Finding with status 'error' or 'no_data' rather than an
    exception that would take the rest of the team down with it.
    """

    KEY = "agent"
    NAME = "Agent"
    LEAD = ""
    ROLE = ""
    USES_LLM = False

    def __init__(self, llm=None):
        self.llm = llm

    def new_finding(self, ctx):
        return Finding(agent=self.KEY, lead=self.LEAD, company=ctx.name)

    def analyse(self, ctx, finding):  # pragma: no cover - abstract
        raise NotImplementedError

    def run(self, ctx):
        f = self.new_finding(ctx)
        t0 = time.time()
        try:
            self.analyse(ctx, f)
        except Exception as e:
            log.error("%s crashed on %s:\n%s", self.KEY, ctx.name, traceback.format_exc())
            f.status = "error"
            f.score, f.confidence = 0.0, 0.0
            f.summary = f"{self.NAME} could not complete: {type(e).__name__}: {e}"
        f.score = clamp(float(f.score or 0.0), -1.0, 1.0)
        f.confidence = clamp(float(f.confidence or 0.0), 0.0, 1.0)
        try:
            from agents import profiles

            profiles.apply(f)
        except Exception:  # a bad profile never costs a finding
            log.exception("agent profile for %s not applied", self.KEY)
        if f.status == "ok" and not f.evidence:
            f.status = "no_data"
            f.confidence = min(f.confidence, 0.1)
        f.seconds = round(time.time() - t0, 2)
        return f

    # ---- helpers shared by subclasses ----
    def ask_llm(self, tier, system, user, max_tokens=600, json_mode=True):
        """-> parsed reply or None. None also when LLMs are off or exhausted."""
        if self.llm is None:
            return None
        from agents import profiles

        tier = profiles.llm_tier(self.KEY, tier)
        if tier is None:  # told to stay rule-based
            return None
        return self.llm.complete(
            tier, system + profiles.instructions_for(self.KEY), user, max_tokens=max_tokens, json_mode=json_mode, agent=self.KEY
        )


def cited(claims, evidence):
    """
    Keep only LLM claims that cite at least one evidence id that exists.

    claims: list of {"text": ..., "evidence": ["E1a2b...", ...]}
    -> (kept, dropped_count)
    """
    ids = {e.id for e in evidence}
    kept, dropped = [], 0
    for c in claims or []:
        if not isinstance(c, dict):
            dropped += 1
            continue
        refs = [r for r in (c.get("evidence") or []) if r in ids]
        if refs and c.get("text"):
            kept.append({"text": str(c["text"])[:400], "evidence": refs})
        else:
            dropped += 1
    return kept, dropped


def weighted_mean(pairs):
    """pairs of (value, weight) -> weighted mean, or None if no weight."""
    tot = sum(w for _, w in pairs if w > 0)
    if tot <= 0:
        return None
    return sum(v * w for v, w in pairs if w > 0) / tot
