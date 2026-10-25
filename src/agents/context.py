"""
CompanyContext: everything the team knows about one company during a run.

Feeds are fetched lazily and memoised, so the first analyst to need the news
downloads it and the next five read the same list. Findings are filed here as
each analyst finishes, which is how the Review team and the Chief read what
the specialists concluded.
"""

import threading

from agents.base import Evidence


class CompanyContext:
    def __init__(self, company, base, rec, feeds, board, run_id, shared):
        self.name = company["name"]
        self.ticker = company.get("ticker") or (rec or {}).get("ticker") or ""
        self.symbol = self.ticker.split(".")[0].upper()
        self.sector = company.get("sector", "")
        self.cap = company.get("cap", "")
        self.base = base  # dict for formula.evaluate
        self.rec = rec  # universe entry from the calculator, or None
        self.feeds = feeds
        self.board = board
        self.run_id = run_id
        self.shared = shared  # run-wide: macro snapshot, peer bases, geo read
        self.findings = {}
        self.leads = {}
        self._memo = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------- memo
    def _get(self, key, fn):
        with self._lock:
            if key in self._memo:
                return self._memo[key]
        val = fn()
        with self._lock:
            self._memo[key] = val
        return val

    @property
    def prices(self):
        return self._get("prices", lambda: self.feeds.prices(self.ticker, 400) if self.ticker else [])

    @property
    def info(self):
        return self._get("info", lambda: self.feeds.info(self.ticker) if self.ticker else {})

    @property
    def statements(self):
        return self._get(
            "statements",
            lambda: self.feeds.statements(self.ticker) if self.ticker else {"annual": {}, "quarterly": []},
        )

    @property
    def annual(self):
        """Merged yearly figures, oldest first: [(fy, dict), ...].

        The extended statement fetch supplies the forensic fields; the
        calculator's own (gap-filled) figures win where both exist, so the
        agents and the valuation models agree on the core numbers."""

        def build():
            years = {}
            for fy, d in (self.statements.get("annual") or {}).items():
                years[int(fy)] = dict(d)
            if self.rec:
                for fy, d in self.rec["data"]["years"].items():
                    row = years.setdefault(int(fy), {})
                    for k, v in (d or {}).items():
                        if not k.startswith("_") and v is not None:
                            row[k] = v
            return sorted(
                ((fy, d) for fy, d in years.items() if d.get("revenue") or d.get("net_income")),
                key=lambda x: x[0],
            )

        return self._get("annual", build)

    @property
    def news(self):
        q = self.name.replace(" Limited", "").replace(" Ltd", "")
        return self._get("news", lambda: self.feeds.news(f'"{q}"'))

    @property
    def announcements(self):
        return self._get("ann", lambda: self.feeds.nse_announcements(self.symbol) if self.symbol else [])

    @property
    def insider(self):
        return self._get("insider", lambda: self.feeds.nse_insider(self.symbol) if self.symbol else [])

    @property
    def shareholding(self):
        return self._get("shp", lambda: self.feeds.nse_shareholding(self.symbol) if self.symbol else [])

    @property
    def last_price(self):
        px = self.prices
        if px:
            return px[-1]["close"]
        i = self.info
        return i.get("currentPrice") or i.get("regularMarketPrice") or i.get("previousClose")

    # ---------------------------------------------------------- evidence
    def news_evidence(self):
        """News items as Evidence, with the credibility weights set by the
        News Credibility analyst once it has run (1.0 until then)."""

        def build():
            weights = self.shared.get("cred_weights", {}).get(self.name, {})
            out = []
            for n in self.news:
                e = Evidence(
                    source=n.get("source") or n.get("domain") or "news",
                    title=n["title"],
                    url=n.get("url", ""),
                    date=n.get("date", ""),
                    kind="news",
                )
                e.credibility = weights.get(e.id, 1.0)
                out.append(e)
            for a in self.announcements:
                if not a.get("title"):
                    continue
                out.append(
                    Evidence(
                        source="NSE corporate announcement",
                        title=(a["title"] + (": " + a["text"][:160] if a.get("text") else "")).strip(),
                        url=a.get("url", ""),
                        date=a.get("date", ""),
                        kind="filing",
                        credibility=1.0,
                    )
                )
            return out

        # rebuilt each call: credibility weights arrive part-way through
        return build()

    def finding(self, key):
        return self.findings.get(key)

    def signal(self, key, name, default=None):
        f = self.findings.get(key)
        if f is None or f.status != "ok":
            return default
        v = f.signals.get(name)
        return default if v is None else v
