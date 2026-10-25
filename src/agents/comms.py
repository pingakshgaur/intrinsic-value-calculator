"""
Agent communications: the roster (who is who), the message bus (what the
agents tell each other) and live status (who is doing what, right now).

How the agents really exchange information
------------------------------------------
For each company the agents share one CompanyContext - the blackboard for
that company. A feed one analyst downloads is memoised and read by the next
(no second request), findings are filed there for the leads, the review team
and the chief, and run-wide facts (macro, credibility weights) live in one
shared dict. That is the cheapest exchange there is: no extra requests and
no extra LLM calls.

The bus makes the exchange visible. Every message is written FROM data the
agents already produced - a finding, a reused feed, a failed validation, a
lead's score - so the chat costs no API calls at all, and writes are batched
into the blackboard (one commit per ~25 messages or per second).

Message kinds
    task      a lead hands the company to its team; the chief opens coverage
    fetch     an analyst pulled a feed from a source               (trace)
    share     an analyst reused data another agent fetched: a call saved (trace)
    finding   an analyst files its finding with its team
    request / reply   a cross-team exchange, sent only where one agent really
                      consumes another's output
    flag      a red flag
    review    validation outcome - DMs only to analysts that failed (exceptions only)
    summary   a lead's team report to the chief
    verdict   the chief's verdict
    system    run start and finish, data-source problems, LLM usage
    user / command   messages and slash-commands typed in the web app

Nomenclature
    TEAM-NN   callsign: TEAM is the three-letter team code, 00 is the team's
              lead (CMD-00 is the chief), 01.. are its analysts in run order.
    #team     each team has a channel; #command is the chief and the five leads;
              #ops is the run orchestrator; dm:A|B is a direct exchange.
"""

import json
import logging
import threading
import time

log = logging.getLogger("agents.comms")

TEAMS = {
    "CMD": {"slug": "command", "name": "Command", "color": "#E0B97F", "channel": "command",
            "purpose": "The chief and the five leads: team reports in, verdicts out."},
    "NWS": {"slug": "nws-market-news", "name": "Market News Research", "color": "#57A3F8", "channel": "nws",
            "purpose": "News and exchange filings: what happened, how credible, how the market took it."},
    "EQR": {"slug": "eqr-equity-research", "name": "Equity Research", "color": "#86CF86", "channel": "eqr",
            "purpose": "The accounts: fundamentals, forensic quality and the next results."},
    "IGR": {"slug": "igr-industry-geo", "name": "Industry & Geopolitical Research", "color": "#F0A35E", "channel": "igr",
            "purpose": "The sector and the world around it: industry trend, macro and geopolitics."},
    "MAO": {"slug": "mao-market-activity", "name": "Market Activity & Ownership", "color": "#4EC9B0", "channel": "mao",
            "purpose": "Who is buying and selling: volume, insiders, funds and short-sellers."},
    "IRV": {"slug": "irv-review", "name": "Independent Research Review", "color": "#AD80D7", "channel": "irv",
            "purpose": "Checks every finding against its evidence, then argues the bull and the bear case."},
    "OPS": {"slug": "ops-run-control", "name": "Operations", "color": "#9A9B9C", "channel": "ops",
            "purpose": "The run orchestrator: start, progress, data-source problems, LLM usage."},
}

# key -> (callsign, team, role, title, duty)
_ROWS = [
    ("chief", "CMD-00", "CMD", "chief", "Chief Market Intelligence Officer",
     "Runs the HYBRID MODEL on the teams' signals and signs each verdict."),
    ("market_news_lead", "NWS-00", "NWS", "lead", "Market News Research Lead",
     "Turns five news analysts into one score for the chief."),
    ("research_analyst", "NWS-01", "NWS", "analyst", "Research Analyst",
     "Reads news and NSE filings; flags governance and legal trouble."),
    ("news_credibility_analyst", "NWS-02", "NWS", "analyst", "News Credibility Analyst",
     "Weights sources and spots promotional coverage."),
    ("sentiment_analyst", "NWS-03", "NWS", "analyst", "Sentiment Analyst",
     "Credibility-weighted tone of the coverage."),
    ("stock_movement_analyst", "NWS-04", "NWS", "analyst", "Stock Movement Analyst",
     "Returns against the Nifty and abnormal moves."),
    ("market_impact_analyst", "NWS-05", "NWS", "analyst", "Market Impact Analyst",
     "Which news actually changes business value."),
    ("equity_research_lead", "EQR-00", "EQR", "lead", "Equity Research Lead",
     "Turns the accounts work into one score for the chief."),
    ("fundamental_research_analyst", "EQR-01", "EQR", "analyst", "Fundamental Research Analyst",
     "Returns on capital, growth, margins and moat."),
    ("financial_forensics_analyst", "EQR-02", "EQR", "analyst", "Financial Forensics Analyst",
     "Piotroski, Altman Z'', Beneish M and accruals."),
    ("pre_earnings_analyst", "EQR-03", "EQR", "analyst", "Pre-Earnings Intelligence Analyst",
     "The quarterly trend into the next results."),
    ("industry_geo_lead", "IGR-00", "IGR", "lead", "Head of Industry & Geopolitical Research",
     "Turns sector and macro work into one score for the chief."),
    ("industry_research_analyst", "IGR-01", "IGR", "analyst", "Industry Research Analyst",
     "Sector index, peers and the sector outlook."),
    ("geopolitical_risk_analyst", "IGR-02", "IGR", "analyst", "Geopolitical Risk Analyst",
     "VIX, the rupee, crude, US yields and geopolitical news."),
    ("market_activity_lead", "MAO-00", "MAO", "lead", "Head of Market Activity & Ownership",
     "Turns trading and ownership work into one score for the chief."),
    ("market_volume_analyst", "MAO-01", "MAO", "analyst", "Market Volume Intelligence Analyst",
     "Liquidity, volume spikes and delivery."),
    ("insider_activity_analyst", "MAO-02", "MAO", "analyst", "Insider Activity Analyst",
     "Promoter and insider trades (SEBI PIT)."),
    ("fund_holdings_analyst", "MAO-03", "MAO", "analyst", "Fund Holdings Research Analyst",
     "Shareholding trend, pledges and institutions."),
    ("short_seller_analyst", "MAO-04", "MAO", "analyst", "Short-Seller Research Analyst",
     "Short reports, allegations and distress."),
    ("review_lead", "IRV-00", "IRV", "lead", "Independent Research Review Lead",
     "Makes sure only validated work reaches the chief."),
    ("research_validation_analyst", "IRV-01", "IRV", "analyst", "Research Validation Analyst",
     "Enforces the evidence rules on every finding."),
    ("bull_case_analyst", "IRV-02", "IRV", "analyst", "Bull Case Analyst",
     "The strongest honest case for the stock."),
    ("bear_case_analyst", "IRV-03", "IRV", "analyst", "Bear Case Analyst",
     "The strongest honest case against the stock."),
    ("orchestrator", "OPS-00", "OPS", "system", "Run Orchestrator",
     "Starts runs, schedules companies, reports data-source problems and LLM usage."),
]

ROSTER = {cs: {"key": k, "callsign": cs, "team": t, "role": r, "title": ti, "duty": d}
          for k, cs, t, r, ti, d in _ROWS}
BY_KEY = {v["key"]: cs for cs, v in ROSTER.items()}
LEAD_OF = {"NWS": "NWS-00", "EQR": "EQR-00", "IGR": "IGR-00", "MAO": "MAO-00", "IRV": "IRV-00", "CMD": "CMD-00"}

# where each analyst's inputs come from (the sources on the network graph)
SOURCES = {
    "SRC-MKT": {"title": "Market data", "detail": "Yahoo Finance: prices, info, holders, earnings dates"},
    "SRC-NSE": {"title": "Exchange filings", "detail": "NSE: announcements, insider trades, shareholding"},
    "SRC-NEWS": {"title": "News wire", "detail": "Google News RSS, credibility-weighted"},
    "SRC-ACC": {"title": "Accounts & valuation", "detail": "The calculator's statements, gap-filling and HYBRID MODEL inputs"},
    "SRC-LLM": {"title": "LLM router", "detail": "Groq / Gemini / NVIDIA free tiers, cached and paced"},
}
INPUTS = {
    "NWS-01": ["SRC-NEWS", "SRC-NSE", "SRC-LLM"], "NWS-02": ["SRC-NEWS"], "NWS-03": ["SRC-NEWS", "SRC-LLM"],
    "NWS-04": ["SRC-MKT"], "NWS-05": ["SRC-NEWS", "SRC-LLM"],
    "EQR-01": ["SRC-ACC", "SRC-MKT"], "EQR-02": ["SRC-ACC"], "EQR-03": ["SRC-ACC", "SRC-MKT"],
    "IGR-01": ["SRC-MKT", "SRC-NEWS", "SRC-LLM"], "IGR-02": ["SRC-MKT", "SRC-NEWS", "SRC-LLM"],
    "MAO-01": ["SRC-MKT", "SRC-NSE"], "MAO-02": ["SRC-NSE", "SRC-MKT"], "MAO-03": ["SRC-NSE", "SRC-MKT"],
    "MAO-04": ["SRC-NEWS", "SRC-LLM"],
    "CMD-00": ["SRC-ACC", "SRC-LLM"],
}
# real cross-agent reads in the code: consumer -> [providers]
CONSUMES = {
    "MAO-04": ["MAO-01", "NWS-04"],                       # short-seller reads volume and relative strength
    "NWS-03": ["NWS-02"], "NWS-05": ["NWS-02"],           # credibility weights feed tone and impact
    "IRV-01": [cs for cs, v in ROSTER.items() if v["role"] == "analyst" and v["team"] != "IRV"],
    "IRV-02": ["NWS-00", "EQR-00", "IGR-00", "MAO-00"], "IRV-03": ["NWS-00", "EQR-00", "IGR-00", "MAO-00", "EQR-02"],
    "CMD-00": ["NWS-00", "EQR-00", "IGR-00", "MAO-00", "IRV-00"],
}
# memo keys in CompanyContext -> the source they come from
FEED_SOURCE = {"prices": "SRC-MKT", "info": "SRC-MKT", "statements": "SRC-ACC", "annual": "SRC-ACC",
               "news": "SRC-NEWS", "ann": "SRC-NSE", "insider": "SRC-NSE", "shp": "SRC-NSE"}
FEED_NAME = {"prices": "400-day price history", "info": "company profile", "statements": "financial statements",
             "annual": "merged yearly accounts", "news": "news pull", "ann": "NSE announcements",
             "insider": "insider trades", "shp": "shareholding pattern"}


def channels():
    out = []
    for code, t in TEAMS.items():
        members = [cs for cs, v in ROSTER.items() if v["team"] == code]
        if code == "CMD":
            members = ["CMD-00"] + [LEAD_OF[c] for c in ("NWS", "EQR", "IGR", "MAO", "IRV")]
        if code == "OPS":
            members = ["OPS-00", "CMD-00"]
        out.append({"id": t["channel"], "name": t["slug"],
                    "team": code, "purpose": t["purpose"], "members": members})
    return out


def roster():
    """Everything the web app needs to draw the workforce."""
    return {
        "teams": TEAMS, "agents": list(ROSTER.values()), "channels": channels(), "sources": SOURCES,
        "inputs": INPUTS, "consumes": CONSUMES,
    }


def dm(a, b):
    return "dm:" + "|".join(sorted([a, b]))


# ---------------------------------------------------------------- who is talking
_local = threading.local()


def set_current(callsign):
    _local.cs = callsign


def current():
    return getattr(_local, "cs", None)


# ---------------------------------------------------------------- the bus
class Bus:
    FLUSH_N, FLUSH_S = 25, 1.0

    def __init__(self, board, run_id, mode, companies):
        self.board, self.run_id, self.mode = board, run_id, mode
        self.lock = threading.Lock()
        self.buf = []
        self.seq = 0
        self.last = time.time()
        self.dirty = set()
        self.status = {cs: {"state": "idle", "companies": [], "task": "", "since": time.time(),
                            "done": 0, "errors": 0, "sent": 0, "received": 0, "llm": 0}
                       for cs in ROSTER}
        self.progress = {"total": companies, "done": 0, "saved": 0, "fetched": 0, "messages": 0,
                         "mode": mode, "started": time.time(), "finished": None}
        self._shared_seen = set()

    # -- writing
    def post(self, sender, channel, text, kind="finding", company=None, to=None, data=None, refs=None):
        with self.lock:
            self.seq += 1
            mid = f"{self.run_id}-{self.seq}"
            self.buf.append((mid, self.run_id, time.time(), channel, sender, to or "", company or "", kind,
                             text, json.dumps(data or {}, default=str), json.dumps(refs or [])))
            st = self.status.get(sender)
            if st:
                st["sent"] += 1
                self.dirty.add(sender)
            for r in ([to] if to else []):
                if r in self.status:
                    self.status[r]["received"] += 1
                    self.dirty.add(r)
            if kind not in ("fetch", "share"):
                self.progress["messages"] += 1
            # run-level news (system, verdicts) goes out at once; chatter is batched
            due = kind in ("system", "verdict") or len(self.buf) >= self.FLUSH_N or time.time() - self.last >= self.FLUSH_S
        if due:
            self.flush()
        return mid

    def flush(self, force=False):
        with self.lock:
            rows, self.buf = self.buf, []
            st = {cs: self.status[cs] for cs in self.dirty}
            self.dirty = set()
            prog = dict(self.progress)
            self.last = time.time()
        if rows or st or force:
            try:
                self.board.save_comms(self.run_id, rows, st, prog)
            except Exception:
                log.exception("agent messages could not be saved")

    # -- status
    def start(self, cs, company, task):
        with self.lock:
            s = self.status[cs]
            if company not in s["companies"]:
                s["companies"].append(company)
            s.update(state="working", task=task, since=time.time())
            self.dirty.add(cs)

    def end(self, cs, company, ok=True, llm=False):
        with self.lock:
            s = self.status[cs]
            if company in s["companies"]:
                s["companies"].remove(company)
            s["done" if ok else "errors"] += 1
            s["llm"] += 1 if llm else 0
            s.update(state="working" if s["companies"] else ("done" if ok else "error"),
                     task=f"Analysing {', '.join(s['companies'])}" if s["companies"] else "", since=time.time())
            self.dirty.add(cs)

    def company_done(self):
        with self.lock:
            self.progress["done"] += 1
        self.flush(force=True)

    def finish(self):
        with self.lock:
            self.progress["finished"] = time.time()
            for cs, s in self.status.items():
                if s["state"] == "working":
                    s.update(state="done", companies=[], task="")
                    self.dirty.add(cs)
        self.flush(force=True)  # the finish time must reach the blackboard even with nothing else to write

    # -- feed traffic (from CompanyContext's memo)
    def fetched(self, cs, key, company, n=None):
        src = FEED_SOURCE.get(key)
        if not src or cs not in ROSTER:
            return
        with self.lock:
            self.progress["fetched"] += 1
        what = FEED_NAME.get(key, key) + (f" ({n} items)" if isinstance(n, int) else "")
        self.post(cs, "trace", f"Pulled the {what} for {company}.", kind="fetch", company=company,
                  data={"source": src, "key": key, "items": n})

    def shared(self, origin, cs, key, company):
        if cs not in ROSTER or origin not in ROSTER or (cs, key, company) in self._shared_seen:
            return
        self._shared_seen.add((cs, key, company))
        with self.lock:
            self.progress["saved"] += 1
        self.post(origin, "trace", f"Shared my {FEED_NAME.get(key, key)} for {company} with @{cs} - no second request.",
                  kind="share", company=company, to=cs, data={"source": FEED_SOURCE.get(key), "key": key})


# ---------------------------------------------------------------- message text
def _pct(x):
    return f"{x:+.0%}" if isinstance(x, (int, float)) else "n/a"


def _money(x):
    return f"₹{x:,.0f}" if isinstance(x, (int, float)) else "n/a"


def finding_text(f):
    if f.status == "error":
        return f"Couldn't finish {f.company}: {f.summary[:200]}"
    if f.status == "no_data":
        return f"Nothing usable on {f.company}: no evidence I could stand behind."
    head = f"{f.company}: score {f.score:+.2f}, confidence {f.confidence:.0%}."
    return f"{head} {f.summary[:420]}".strip()


def finding_data(f):
    sig = {k: v for k, v in (f.signals or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return {
        "score": f.score, "confidence": f.confidence, "status": f.status, "used_llm": f.used_llm,
        "validated": f.validated, "flags": f.flags[:6], "signals": dict(list(sig.items())[:8]),
        "evidence": [{"id": e.id, "source": e.source, "title": e.title[:160], "url": e.url, "date": e.date}
                     for e in f.evidence[:5]],
        "evidence_count": len(f.evidence), "seconds": f.seconds,
    }


def summary_text(rep, company):
    return (f"{company}: team score {rep['score']:+.2f} at {rep['confidence']:.0%} confidence, "
            f"{rep['usable']}/{rep['analysts']} findings usable. {rep['summary'][:320]}")


def verdict_text(v):
    up = v.get("upside")
    flags = len(v.get("red_flags") or [])
    return (f"{v['company']}: {v.get('label')}. HYBRID MODEL {_money(v.get('expected_value'))} vs price "
            f"{_money(v.get('price'))} ({_pct(up)}), confidence {v.get('confidence') or 0:.0f}, "
            f"buy-below {_money(v.get('buy_below'))}" + (f", {flags} red flag(s)." if flags else ", no red flags."))
