"""
One research cycle, start to finish.

    1  base valuation   the calculator's own engine (fetch, gap-fill, peer
                        tables, DCF / P/E / EV / Graham / RI, Hybrid) for the
                        latest complete financial year
    2  specialists      News, Equity, Industry & Geo, Market Activity teams
    3  review           Validation, then Bull and Bear
    4  chief            formula + verdict + executive summary
    5  outputs          blackboard rows, Markdown / JSON / HTML reports,
                        change alerts

FULL vs QUICK

    full    everything above. Run once a day after the close.
    quick   reuses the last full run's base valuation and the slow-moving
            findings (fundamentals, forensics, pre-earnings, industry, macro)
            and re-runs only the fast-moving teams - news and market
            activity - then review and the chief. Cheap enough to run
            several times a day on free tiers.
"""

import concurrent.futures as cf
import datetime as dt
import logging
import time

import config

from agents import chief, comms, protocol
from agents import settings as S
from agents.base import Finding
from agents.blackboard import Blackboard
from agents.context import CompanyContext
from agents.feeds import Feeds
from agents.llm import LLMRouter
from agents import team_news, team_equity, team_industry, team_market, team_review

log = logging.getLogger("agents.runner")

TEAMS = [
    ("market_news_lead", team_news.TEAM),
    ("equity_research_lead", team_equity.TEAM),
    ("industry_geo_lead", team_industry.TEAM),
    ("market_activity_lead", team_market.TEAM),
]
REVIEW = ("review_lead", team_review.TEAM)
# re-used, not re-run, in a quick sweep
SLOW_AGENTS = {
    "fundamental_research_analyst", "financial_forensics_analyst", "pre_earnings_analyst",
    "industry_research_analyst", "geopolitical_risk_analyst",
}


def all_agents():
    """[(lead, AgentClass)] in the order they run."""
    return [(lead, a) for lead, team in TEAMS + [REVIEW] for a in team]


# ======================================================== base valuation
def make_base(rec, rows, live_price):
    """
    The HYBRID MODEL's inputs for the latest year that has the Ensemble's
    components, priced at the live quote. -> (base, signals from accounts).
    """
    import hybrid_model as HM

    mine = [r for r in rows if "_comps" in r and r["company"] in (rec.get("_name"),)]
    if not mine:
        return {"price": live_price, "sector": rec["sector"]}, HM.NEUTRAL
    row = max(mine, key=lambda r: r["fy"])
    base = HM.base_from_record(rec, row["fy"], row["_comps"], price=live_price, regime=row.get("_regime"))
    # calibrated on every earlier year of the whole panel, like the report
    base["lens_calibration"] = rec.get("_calibration") or {}
    base["k_capm"] = HM.cost_of_equity(base, HM.NEUTRAL, HM.Params())[0]
    sig = HM.signals_from_accounts(rec["data"]["years"], row["fy"], base["k_capm"])
    return base, sig


def base_valuation(companies, feeds, offline=False, ml=False):
    """-> ({name: base}, {name: accounts signals}, {name: universe rec})"""
    import capital
    import estimation
    import hybrid_model as HM
    import ml_common
    import model_ev_ebitda
    import model_pe
    import model_registry
    import overrides
    import pipeline

    latest = config.latest_complete_fy()
    span = int(S.num("run.history_years", 5))
    config.set_fy_range(latest - span + 1, latest)
    if offline:
        import mock_source
        import ticker_resolver

        config.OFFLINE = True
        ticker_resolver.resolve = mock_source.resolve
    overrides.load()

    print(f"[agents] base valuation FY{config.FY_START}-FY{config.FY_END} for {len(companies)} companies")
    universe, failures = pipeline.build_universe(companies)
    estimation.fill_universe(universe)
    pe_table = model_pe.build_sector_pe_table(universe) if universe else {}
    ev_table = model_ev_ebitda.build_sector_table(universe) if universe else {}
    capital.build_sector_betas(universe)

    ml_modules = pipeline.active_ml_modules() if ml and config.ML_ENABLED else []
    ml_keys = {m.key for m in model_registry.ml_models()}
    enabled = {k for k in model_registry.enabled_keys() if ml_modules or k not in ml_keys}
    # the HYBRID MODEL itself is evaluated by the chief with the agents'
    # signals; here only the Ensemble's components are needed
    enabled.discard("hybrid_model")
    enabled.add("ensemble")
    ctx = {
        "valued": [c for c in companies if c["name"] in universe],
        "universe": universe, "failures": failures, "peer_universe": universe,
        "pe_table": pe_table, "ev_table": ev_table, "ml_modules": ml_modules, "enabled": enabled,
    }
    store = None
    if ml_modules:
        df, fails = ml_common.build_dataset(universe)
        store = ml_common.run_models(df, [m.SPEC for m in ml_modules], fails)
    rows, _ = pipeline.value_rows(ctx, store, write_hybrid=False)

    # lens calibration for each company's latest year, learned from all the
    # earlier company-years in this panel
    import model_hybrid_model as HMM

    calibrate = bool(HM.Params().get("calibration.enabled", True))
    hist = HMM._history(rows, universe) if calibrate else []
    for name, rec in universe.items():
        latest_fy = max((r["fy"] for r in rows if r["company"] == name and "_comps" in r), default=None)
        if latest_fy is not None and calibrate:
            # the latest year may learn from itself here: it is the most
            # recent evidence and no later price is being predicted from it
            rec["_calibration"] = HM.lens_calibration(hist, rec["sector"], latest_fy + 1)

    bases, signals = {}, {}
    for c in companies:
        rec = universe.get(c["name"])
        if rec is None:
            px = feeds.prices(c.get("ticker"), 10) if c.get("ticker") and not offline else []
            bases[c["name"]] = {"sector": c.get("sector", ""), "price": px[-1]["close"] if px else None}
            signals[c["name"]] = HM.NEUTRAL
            continue
        # offline, every mock company shares one synthetic ticker, so its own
        # mock FY price is the only meaningful one
        px = [] if offline else feeds.prices(rec["ticker"], 10)
        live = px[-1]["close"] if px else None
        try:
            rec["_name"] = c["name"]
            bases[c["name"]], signals[c["name"]] = make_base(rec, rows, live)
        except Exception as e:
            log.exception("base inputs failed for %s", c["name"])
            print(f"[agents] base inputs failed for {c['name']}: {type(e).__name__}: {e}")
            bases[c["name"]], signals[c["name"]] = {"sector": c.get("sector", ""), "price": live}, HM.NEUTRAL
    return bases, signals, universe


# ======================================================== one company
def _run_analyst(cls, llm, ctx, bus):
    """One analyst, with its live status and its finding filed on the bus."""
    cs = comms.BY_KEY.get(cls.KEY)
    if bus and cs:
        bus.start(cs, ctx.name, f"Analysing {ctx.name}")
    comms.set_current(cs)
    try:
        f = cls(llm).run(ctx)
    finally:
        comms.set_current(None)
    if bus and cs:
        bus.end(cs, ctx.name, ok=f.status != "error", llm=f.used_llm)
    return f


def research_company(company, base, rec, feeds, board, llm, run_id, shared, quick, account_signals=None, bus=None):
    ctx = CompanyContext(company, base, rec, feeds, board, run_id, shared)
    ctx.account_signals = account_signals or {}
    ctx.bus = bus
    reuse = board.last_findings(ctx.name, SLOW_AGENTS) if quick else {}
    mids = {}  # agent key -> its finding's message id (a lead's report refers to them)
    if bus:
        protocol.open_company(bus, ctx)

    for lead, team in TEAMS:
        active = [c for c in team if chief.analyst_weight(lead, c.KEY) > 0]
        if bus:
            protocol.assign(bus, lead, [c.KEY for c in active], ctx, SLOW_AGENTS & set(reuse) if quick else ())
        for cls in active:
            cs = comms.BY_KEY.get(cls.KEY)
            if quick and cls.KEY in SLOW_AGENTS:
                if cls.KEY in reuse:
                    f = Finding.from_dict(reuse[cls.KEY])
                    f.notes.append("re-used from the last full run")
                    ctx.findings[cls.KEY] = f
                    if bus and cs:
                        mids[cls.KEY] = protocol.analyst_done(bus, cs, f, ctx, reused=True)
                continue
            if bus and cs:
                protocol.consult(bus, cs, ctx)
            ctx.findings[cls.KEY] = _run_analyst(cls, llm, ctx, bus)
            if bus and cs:
                mids[cls.KEY] = protocol.analyst_done(bus, cs, ctx.findings[cls.KEY], ctx)
                protocol.exchanges(bus, cs, ctx)
        chief.lead_report(ctx, lead)

    lead, team = REVIEW
    for cls in team:
        if chief.analyst_weight(lead, cls.KEY) <= 0 and cls.KEY != "research_validation_analyst":
            continue
        if bus and cls.KEY == "bull_case_analyst":
            protocol.cases(bus, ctx)  # bull and bear both ask the leads before writing
        ctx.findings[cls.KEY] = _run_analyst(cls, llm, ctx, bus)
        cs = comms.BY_KEY.get(cls.KEY)
        if bus and cs:
            mids[cls.KEY] = protocol.analyst_done(bus, cs, ctx.findings[cls.KEY], ctx)
            if cls.KEY == "research_validation_analyst":
                protocol.review(bus, ctx)
    # validation changed which findings count, so every lead re-scores
    for lead_key, _ in TEAMS + [REVIEW]:
        chief.lead_report(ctx, lead_key)
    reports = protocol.team_reports(bus, ctx, mids) if bus else {}

    def ask(tier, system, user, max_tokens=600):
        return llm.complete(tier, system, user, max_tokens=max_tokens, agent="chief") if llm else None

    if bus:
        bus.start("CMD-00", ctx.name, f"Deciding {ctx.name}")
    comms.set_current("CMD-00")
    try:
        verdict = chief.decide(ctx, ask)
    finally:
        comms.set_current(None)
    if bus:
        bus.end("CMD-00", ctx.name, ok=True, llm=(verdict.get("summary") or {}).get("by") == "llm")
        protocol.chief(bus, ctx, verdict, reports)
        bus.company_done()
    # dicts too: lens_calibration is one, and a base without it re-evaluates
    # uncalibrated (quick sweeps, the Studio, live prices)
    verdict["base"] = {k: v for k, v in base.items() if isinstance(v, (int, float, str, list, dict, type(None)))}
    verdict["account_signals"] = ctx.account_signals

    for f in ctx.findings.values():
        board.save_finding(run_id, f)
    prev = board.previous_verdict(ctx.name, run_id)
    verdict["changes"] = changes_since(prev, verdict)
    board.save_verdict(run_id, verdict)
    verdict["history"] = board.history(ctx.name)
    return verdict


def changes_since(prev, v):
    if not prev:
        return ["first research run for this company"]
    out = []
    if prev.get("label") != v.get("label"):
        out.append(f"label changed: {prev.get('label')} -> {v.get('label')}")
    old = {f.split(" - ")[0] for f in prev.get("red_flags", [])}
    for fl in v.get("red_flags", []):
        if fl.split(" - ")[0] not in old:
            out.append(f"NEW red flag: {fl}")
    bb, p0, p1 = prev.get("buy_below"), prev.get("price"), v.get("price")
    if bb and p0 and p1 and p0 > bb >= p1:
        out.append(f"price {p1:,.2f} fell below the research buy-below level {bb:,.2f}")
    e0, e1 = prev.get("expected_value"), v.get("expected_value")
    if e0 and e1 and abs(e1 / e0 - 1) > 0.10:
        out.append(f"expected value moved {e1 / e0 - 1:+.0%} ({e0:,.2f} -> {e1:,.2f})")
    return out


# ======================================================== the run
def run_agents(companies, offline=False, use_llm=True, quick=False, only=None, ml=None):
    # settings are loaded by the caller (run.py honours --agent-settings);
    # S.data() only loads the default file if nobody has yet
    S.data()
    S.load_dotenv()
    t0 = time.time()
    state = S.state_dir()
    board = Blackboard(state / "blackboard.sqlite")
    llm = LLMRouter(board, enabled=use_llm and not offline)
    feeds = Feeds(offline=offline)

    only = [t.upper() for t in (only or S.get("run.only_tickers", []) or [])]
    if only:
        wanted = {t.split(".")[0] for t in only}
        companies = [c for c in companies if (c.get("ticker") or "").upper().split(".")[0] in wanted]
        found = {(c.get("ticker") or "").upper().split(".")[0] for c in companies}
        if wanted - found:
            print(f"[agents] not in the companies list, skipped: {', '.join(sorted(wanted - found))} "
                  f"(add them to {S.get('run.companies_csv', 'data/companies.csv')} with a sector)")
    if not companies:
        print("[agents] no companies to research")
        return None

    mode = "quick" if quick else "full"
    run_id = board.start_run(mode, len(companies))
    print(f"[agents] run #{run_id} ({mode}) - {len(companies)} companies - {llm.describe()}")
    bus = comms.Bus(board, run_id, mode, len(companies))
    bus.post("OPS-00", "ops", f"Run #{run_id} started: {mode} research on {len(companies)} companies. "
             f"LLM: {llm.describe()}. Feeds are shared per company, so each source is called once.",
             kind="system", data={"mode": mode, "companies": len(companies), "llm": llm.describe()})

    bases, acc_sigs, universe = {}, {}, {}
    if quick:
        for c in companies:
            prev = board.previous_verdict(c["name"], run_id)
            if prev and prev.get("base"):
                b = dict(prev["base"])
                px = feeds.prices(c.get("ticker"), 10) if c.get("ticker") and not offline else []
                if px:
                    b["price"] = px[-1]["close"]
                    if b.get("shares"):
                        b["market_cap"] = b["price"] * b["shares"]
                        b["market_cap_cr"] = b["market_cap"] / 1e7
                bases[c["name"]] = b
                acc_sigs[c["name"]] = prev.get("account_signals") or {}
        missing = [c for c in companies if c["name"] not in bases]
        if missing:
            print(f"[agents] {len(missing)} companies have no earlier full run - valuing them now")
            b2, s2, universe = base_valuation(missing, feeds, offline, bool(ml if ml is not None else S.get("run.base_valuation_ml", False)))
            bases.update(b2)
            acc_sigs.update(s2)
    else:
        bases, acc_sigs, universe = base_valuation(
            companies, feeds, offline, bool(ml if ml is not None else S.get("run.base_valuation_ml", False))
        )

    shared = {
        "as_of": dt.date.today().isoformat(),
        "bases": bases,
        "nifty_prices": feeds.prices("^NSEI", 400),
    }

    verdicts = []
    workers = max(1, int(S.num("run.parallel_companies", 3)))
    print(f"[agents] researching: {len(all_agents())} analysts + 5 leads + chief per company, "
          f"{workers} companies at a time")
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(research_company, c, bases.get(c["name"], {}), universe.get(c["name"]),
                        feeds, board, llm, run_id, shared, quick, acc_sigs.get(c["name"]), bus): c
            for c in companies
        }
        bus.post("OPS-00", "ops", f"Base valuation ready for {len(bases)} companies; researching {workers} at a time.",
                 kind="system", data={"workers": workers})
        for fut in cf.as_completed(futs):
            c = futs[fut]
            try:
                v = fut.result()
                verdicts.append(v)
                ev = v.get("expected_value")
                print(f"[agents] {c['name'][:38]:38s} {v['label']:22s} "
                      f"price {v['price'] or 0:>10,.2f}  value {ev or 0:>10,.2f}  conf {v['confidence']:3.0f}")
            except Exception as e:
                log.exception("research failed for %s", c["name"])
                print(f"[agents] {c['name']}: FAILED {type(e).__name__}: {e}")
                bus.post("OPS-00", "ops", f"{c['name']}: research failed - {type(e).__name__}: {str(e)[:200]}",
                         kind="system", company=c["name"], data={"error": True})
                bus.company_done()

    order = {c["name"]: i for i, c in enumerate(companies)}
    verdicts.sort(key=lambda v: order.get(v["company"], 0))

    from agents import report, notify

    meta = {
        "run_id": run_id, "mode": mode, "started": dt.datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0), "llm": llm.stats(), "llm_mode": llm.describe(),
        "feed_problems": feeds.problems[:30], "companies": len(companies),
    }
    paths = report.write_all(verdicts, meta, state)
    sent = notify.send_changes(verdicts, meta)

    labels = {}
    for v in verdicts:
        labels[v.get("label")] = labels.get(v.get("label"), 0) + 1
    mix = ", ".join(f"{n} {k.lower()}" for k, n in sorted(labels.items(), key=lambda kv: -kv[1]) if k)
    movers = sorted((v for v in verdicts if isinstance(v.get("upside"), (int, float))), key=lambda v: -v["upside"])
    bus.post("CMD-00", "command", f"Run #{run_id} closed: {len(verdicts)} verdicts - {mix}."
             + (f" Widest gap: {movers[0]['company']} ({movers[0]['upside']:+.0%})." if movers else ""),
             kind="verdict", data={"labels": labels, "run": run_id})
    for p in feeds.problems[:5]:
        bus.post("OPS-00", "ops", f"Data source problem: {str(p)[:220]}", kind="system", data={"problem": True})
    st = llm.stats() if hasattr(llm, "stats") else {}
    bus.post("OPS-00", "ops", f"Run #{run_id} finished in {meta['seconds']}s. LLM calls {llm.calls} "
             f"(cache hits {llm.cache_hits}); {bus.progress['saved']} feed requests saved by sharing between agents.",
             kind="system", data={"seconds": meta["seconds"], "llm_calls": llm.calls, "cache_hits": llm.cache_hits,
                                  "saved": bus.progress["saved"], "llm": st})
    bus.finish()
    board.finish_run(run_id, llm.calls, note=f"{len(verdicts)} verdicts")
    board.prune()
    board.close()

    print(f"\n[agents] done in {meta['seconds']}s; LLM calls {llm.calls} (cache hits {llm.cache_hits})")
    if feeds.problems:
        print(f"[agents] {len(feeds.problems)} data-source problem(s); first: {feeds.problems[0]}")
    for p in paths:
        print(f"[agents] wrote {p}")
    if sent:
        print(f"[agents] {sent}")
    return {"verdicts": verdicts, "meta": meta, "paths": paths}
