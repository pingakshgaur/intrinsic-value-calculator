import { ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Cell, Pie, PieChart, Tooltip } from "recharts";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useIntel, useJobs, useMetrics, useStatus } from "../lib/hooks";
import { IndexQuote, isOpen, LiveAlert, MarketStatus, useIndices, useLearning, useLiveAlerts, useWatchlist, useWatchlists, WatchItem } from "../lib/live";
import { useAgentRuns } from "../lib/agents";
import { useScope } from "../lib/scope";
import { ago, duration, isNum, money, num, pct, pctUnits, shortName } from "../lib/format";
import { companyPath } from "../lib/company";
import { HM, HM_COLOR, modelColor } from "../lib/labels";
import { Icon, LabelBadge, PageHeader, Popover } from "../components/ui";
import { Spark } from "../components/Spark";
import { ScopeNote } from "../components/ScopePicker";
import { ResearchLauncher } from "../components/ResearchLauncher";
import { jobTitle } from "../components/Shell";

/**
 * The dashboard: everything worth keeping an eye on, on one page - the market,
 * your watchlists, what is in the buy zone, alerts, the research, running jobs
 * and how accurate the models are. Every widget can be hidden and reordered
 * (with buttons, so it works from the keyboard); the layout is kept per browser.
 * A watchlist picked in the top bar narrows every widget to its companies.
 */

type WidgetId = "pulse" | "buyzone" | "movers" | "alerts" | "research" | "activity" | "markets" | "lists" | "models";
const WIDGETS: { id: WidgetId; title: string; desc: string; span: 4 | 6 | 12 }[] = [
  { id: "pulse", title: "At a glance", desc: "The headline numbers", span: 12 },
  { id: "models", title: "Model health", desc: "Accuracy and the learning pool · click a slice for its page", span: 12 },
  { id: "buyzone", title: "Buy zone", desc: "At or near the HYBRID MODEL buy-below", span: 6 },
  { id: "movers", title: "Movers today", desc: "Biggest moves on your watchlists", span: 6 },
  { id: "alerts", title: "Alerts", desc: "Levels, buy-below and big moves", span: 4 },
  { id: "research", title: "Research", desc: "Gaps to value and red flags", span: 4 },
  { id: "activity", title: "Activity", desc: "Jobs, runs and schedules", span: 4 },
  { id: "markets", title: "Markets", desc: "Indices and sectors", span: 6 },
  { id: "lists", title: "Watchlists", desc: "How each list is doing today", span: 6 },
];
const KEY = "intval.dashboard.v2";
// v1 kept model health last; a layout saved then has it lifted under the headline band once
const OLD_KEY = "intval.dashboard.v1";
interface Layout { order: WidgetId[]; hidden: WidgetId[] }
const DEFAULT: Layout = { order: WIDGETS.map((w) => w.id), hidden: [] };

function readLayout(): Layout {
  try {
    const saved = localStorage.getItem(KEY);
    const v = JSON.parse(saved || localStorage.getItem(OLD_KEY) || "null") as Layout | null;
    if (!v || !Array.isArray(v.order)) return DEFAULT;
    const known = new Set(WIDGETS.map((w) => w.id));
    const order = v.order.filter((id) => known.has(id));
    if (!saved && order.includes("models")) {
      order.splice(order.indexOf("models"), 1);
      order.splice(order.indexOf("pulse") + 1, 0, "models");
    }
    // widgets added in a later version join at the end
    for (const w of WIDGETS) if (!order.includes(w.id)) order.push(w.id);
    return { order, hidden: (v.hidden ?? []).filter((id) => known.has(id)) };
  } catch {
    return DEFAULT;
  }
}

function useLayout() {
  const [layout, setLayout] = useState<Layout>(readLayout);
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(layout)); } catch { /* private mode */ } }, [layout]);
  return [layout, setLayout] as const;
}

const chgClass = (v: unknown) => (isNum(v) ? (v > 0 ? "up" : v < 0 ? "down" : "") : "faint");
const startOfToday = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime() / 1000; };

export function Dashboard() {
  const scope = useScope();
  const [layout, setLayout] = useLayout();
  const [said, setSaid] = useState("");

  const indices = useIndices();
  const all = useWatchlist(null);
  const lib = useWatchlists();
  const alerts = useLiveAlerts();
  const intel = useIntel();
  const status = useStatus();
  const jobs = useJobs(!!status.data?.active_job);
  const runs = useAgentRuns();
  const metrics = useMetrics();
  const learning = useLearning();
  const autostart = useQuery({ queryKey: ["autostart"], queryFn: () => api.get<{ settings: { enabled: boolean; mode: string } }>("/api/agents/autostart"), refetchInterval: 60_000 });

  // a watchlist in focus narrows every widget to its companies
  const items = useMemo(() => (all.data?.items ?? []).filter((w) => !scope.list || (w.lists ?? []).includes(scope.list.id)), [all.data, scope.list]);
  const verdicts = useMemo(() => (intel.data?.verdicts ?? []).filter((v) => scope.has({ ticker: v.ticker, company: v.company })), [intel.data, scope]);
  const myAlerts = useMemo(() => (alerts.data ?? []).filter((a) => scope.has({ ticker: a.ticker, name: a.name })), [alerts.data, scope]);
  const market = indices.data?.market ?? all.data?.tracker.market;

  const visible = layout.order.filter((id) => !layout.hidden.includes(id));
  const ctx: Ctx = { items, verdicts, alerts: myAlerts, market, indices: indices.data?.indices ?? [], sectors: indices.data?.sectors ?? [],
    lists: lib.data?.lists ?? [], allItems: all.data?.items ?? [], loading: all.isLoading };

  return (
    <div className="page dash">
      <PageHeader crumbs={[{ label: "Analysis" }, { label: "Dashboard" }]} title="Dashboard"
        sub={<span className="row" style={{ gap: 10, flexWrap: "wrap" }}>
          <span className={`live-dot ${isOpen(market) ? "on" : ""}`}>{marketLine(market)}</span>
          <span className="faint">{scope.list ? `Showing “${scope.list.name}”` : "Showing every watchlist"}</span>
        </span>}
        actions={<>
          <Customize layout={layout} setLayout={setLayout} announce={setSaid} />
          <ResearchLauncher />
        </>} />
      <ScopeNote />
      {/* the polite region exists before anything is said into it */}
      <div role="status" className="sr-only">{said}</div>

      {visible.length === 0 ? (
        <div className="dash-none">
          <p>Every widget is hidden.</p>
          <button className="btn sec" onClick={() => setLayout(DEFAULT)}>Show the default dashboard</button>
        </div>
      ) : (
        <div className="dash-grid">
          {visible.map((id) => {
            const w = WIDGETS.find((x) => x.id === id)!;
            const body = {
              pulse: <Pulse ctx={ctx} />,
              buyzone: <BuyZone items={ctx.items} loading={ctx.loading} />,
              movers: <Movers items={ctx.items} loading={ctx.loading} />,
              alerts: <Alerts alerts={ctx.alerts} />,
              research: <Research verdicts={ctx.verdicts} total={intel.data?.verdicts.length ?? 0} />,
              activity: <Activity active={status.data?.active_job ?? null} jobs={jobs.data ?? []} run={runs.data?.[0]}
                autostart={autostart.data?.settings} feed={learning.data?.settings} />,
              markets: <Markets indices={ctx.indices} sectors={ctx.sectors} error={indices.isError} />,
              lists: <Lists lists={ctx.lists} items={ctx.allItems} />,
              models: <Models metrics={metrics.data?.overall ?? []} wins={metrics.data?.win_rate ?? []} learning={learning.data} />,
            }[id];
            const link = LINKS[id];
            return (
              <section key={id} className={`dash-w s${w.span}`} aria-labelledby={`dw-${id}`}>
                {id !== "pulse" && (
                  <header className="dash-h">
                    <h2 id={`dw-${id}`}>{w.title}</h2>
                    <span className="dash-d">{w.desc}</span>
                    {link && <Link className="dash-more" to={link.to}>{link.label}<Icon name="arrow-right" className="xs" /></Link>}
                  </header>
                )}
                {id === "pulse" && <h2 id="dw-pulse" className="sr-only">{w.title}</h2>}
                {body}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

const LINKS: Partial<Record<WidgetId, { to: string; label: string }>> = {
  buyzone: { to: "/watchlist", label: "Watchlists" },
  movers: { to: "/markets", label: "Markets" },
  alerts: { to: "/watchlist", label: "All alerts" },
  research: { to: "/", label: "Command Center" },
  activity: { to: "/operations", label: "Operations" },
  markets: { to: "/markets", label: "Markets" },
  lists: { to: "/watchlist", label: "Manage" },
  models: { to: "/performance", label: "Model Performance" },
};

interface Ctx {
  items: WatchItem[]; allItems: WatchItem[]; verdicts: NonNullable<ReturnType<typeof useIntel>["data"]>["verdicts"]; alerts: LiveAlert[];
  market: MarketStatus | undefined;
  indices: IndexQuote[]; sectors: IndexQuote[]; lists: NonNullable<ReturnType<typeof useWatchlists>["data"]>["lists"]; loading: boolean;
}

function marketLine(m: Ctx["market"]) {
  if (!m) return "Market status loading…";
  const state = m.state === "open" ? "NSE open" : m.state === "pre-open" ? "NSE pre-open" : "NSE closed";
  return `${state} · ${m.ist} IST`;
}

/* ------------------------------------------------------------ customise */
function Customize({ layout, setLayout, announce }: { layout: Layout; setLayout: (l: Layout) => void; announce: (s: string) => void }) {
  const move = (id: WidgetId, by: -1 | 1) => {
    const order = [...layout.order];
    const i = order.indexOf(id), j = i + by;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    setLayout({ ...layout, order });
    announce(`${WIDGETS.find((w) => w.id === id)!.title} moved to position ${j + 1} of ${order.length}`);
  };
  const toggle = (id: WidgetId, on: boolean) => {
    setLayout({ ...layout, hidden: on ? layout.hidden.filter((h) => h !== id) : [...layout.hidden, id] });
    announce(`${WIDGETS.find((w) => w.id === id)!.title} ${on ? "shown" : "hidden"}`);
  };
  return (
    <Popover className="pop dash-cust" trigger={(open, t) => (
      <button className={`btn sec ${open ? "on" : ""}`} onClick={t} aria-expanded={open}><Icon name="layout" className="sm" />Customise</button>
    )}>
      {() => (
        <div className="dash-cust-b">
          <div className="dash-cust-h"><b>Widgets</b><span className="xs faint">Show, hide and reorder. Kept in this browser.</span></div>
          <ol className="dash-cust-l">
            {layout.order.map((id, i) => {
              const w = WIDGETS.find((x) => x.id === id)!;
              const on = !layout.hidden.includes(id);
              return (
                <li key={id}>
                  <label className="dash-cust-n">
                    <input type="checkbox" className="cb" checked={on} onChange={(e) => toggle(id, e.target.checked)} />
                    <span><b>{w.title}</b><small>{w.desc}</small></span>
                  </label>
                  <button className="ibtn sm" onClick={() => move(id, -1)} disabled={i === 0} aria-label={`Move ${w.title} up`} title="Move up"><Icon name="arrow-up" className="xs" /></button>
                  <button className="ibtn sm" onClick={() => move(id, 1)} disabled={i === layout.order.length - 1} aria-label={`Move ${w.title} down`} title="Move down"><Icon name="arrow-down" className="xs" /></button>
                </li>
              );
            })}
          </ol>
          <button className="btn xs ghost" onClick={() => { setLayout(DEFAULT); announce("Dashboard reset to the default layout"); }}><Icon name="discard" className="xs" />Reset to default</button>
        </div>
      )}
    </Popover>
  );
}

/* ------------------------------------------------------------ widgets */
function Pulse({ ctx }: { ctx: Ctx }) {
  const nifty = ctx.indices.find((i) => /NIFTY 50/i.test(i.name));
  const moved = ctx.items.map((w) => w.quote?.chg_pct).filter(isNum) as number[];
  const adv = moved.filter((v) => v > 0).length, dec = moved.filter((v) => v < 0).length;
  const zone = ctx.items.filter((w) => inZone(w)).length;
  const today = ctx.alerts.filter((a) => a.t >= startOfToday()).length;
  const flags = ctx.verdicts.reduce((a, v) => a + (v.red_flags?.length ?? 0), 0);
  return (
    <div className="band dash-band">
      <div><div className="k">Market</div><div className="v">{ctx.market ? (ctx.market.state === "open" ? "Open" : ctx.market.state === "pre-open" ? "Pre-open" : "Closed") : "–"}</div>
        <div className="s">{ctx.market ? `${ctx.market.ist} IST` : "loading…"}</div></div>
      <div><div className="k">NIFTY 50</div><div className="v">{nifty && isNum(nifty.last) ? num(nifty.last, 0) : "–"}</div>
        <div className={`s ${chgClass(nifty?.chg_pct)}`}>{nifty && isNum(nifty.chg_pct) ? `${pct(nifty.chg_pct, 2, true)} today` : "no quote"}</div></div>
      <div><div className="k">Breadth</div><div className="v">{adv}<span className="dash-of"> / {dec}</span></div><div className="s">advancing / declining</div></div>
      <div><div className="k">In the buy zone</div><div className={`v ${zone ? "up" : ""}`}>{zone}</div><div className="s">below the buy-below</div></div>
      <div><div className="k">Alerts today</div><div className={`v ${today ? "warn" : ""}`}>{today}</div><div className="s">{ctx.alerts.length} in all</div></div>
      <div><div className="k">Researched</div><div className="v">{ctx.verdicts.length}</div><div className={`s ${flags ? "down" : ""}`}>{flags ? `${flags} red flags` : "no red flags"}</div></div>
    </div>
  );
}

const gapOf = (w: WatchItem) => {
  const bb = w.quote?.hm?.buy_below, last = w.quote?.last;
  return isNum(bb) && isNum(last) && bb > 0 ? last / bb - 1 : null;
};
const inZone = (w: WatchItem) => { const g = gapOf(w); return g != null && g <= 0; };

function BuyZone({ items, loading }: { items: WatchItem[]; loading: boolean }) {
  const rows = items.map((w) => ({ w, g: gapOf(w) })).filter((r) => r.g != null && r.g <= 0.1).sort((a, b) => a.g! - b.g!).slice(0, 8);
  const priced = items.some((w) => isNum(w.quote?.hm?.buy_below));
  if (!rows.length) return <Quiet loading={loading} icon="tag">{!items.length ? "Add companies to a watchlist to watch their buy zone." : priced ? "No watched company is within 10% of its buy-below price." : "Run a valuation report or research to get buy-below prices."}</Quiet>;
  return (
    <ul className="dash-rows">
      {rows.map(({ w, g }) => (
        <li key={w.ticker}>
          <Link className="dash-row" to={companyPath(w.name)}>
            <span className="dash-co"><b className="ellipsis">{shortName(w.name)}</b><small className="mono">{w.ticker}</small></span>
            <span className="dash-num"><b>{money(w.quote?.last)}</b><small>buy-below {money(w.quote?.hm?.buy_below, 0)}</small></span>
            <span className={`dash-tag ${g! <= 0 ? "in" : "near"}`}>{g! <= 0 ? <><Icon name="check" className="xs" />{pct(-g!, 0)} below</> : <>{pct(g, 0)} above</>}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Movers({ items, loading }: { items: WatchItem[]; loading: boolean }) {
  const [side, setSide] = useState<"up" | "down">("up");
  const moved = items.filter((w) => isNum(w.quote?.chg_pct));
  const rows = [...moved].sort((a, b) => (side === "up" ? b.quote!.chg_pct! - a.quote!.chg_pct! : a.quote!.chg_pct! - b.quote!.chg_pct!))
    .filter((w) => (side === "up" ? w.quote!.chg_pct! > 0 : w.quote!.chg_pct! < 0)).slice(0, 7);
  return (
    <>
      <div className="seg dash-seg" role="group" aria-label="Show">
        <button className={side === "up" ? "on" : ""} aria-pressed={side === "up"} onClick={() => setSide("up")}><Icon name="arrow-up" className="xs" />Gainers</button>
        <button className={side === "down" ? "on" : ""} aria-pressed={side === "down"} onClick={() => setSide("down")}><Icon name="arrow-down" className="xs" />Losers</button>
      </div>
      {!rows.length ? <Quiet loading={loading} icon="pulse">{!items.length ? "Add companies to a watchlist to see their moves." : side === "up" ? "Nothing on your watchlists is up today." : "Nothing on your watchlists is down today."}</Quiet> : (
        <ul className="dash-rows">
          {rows.map((w) => (
            <li key={w.ticker}>
              <Link className="dash-row" to={companyPath(w.name)}>
                <span className="dash-co"><b className="ellipsis">{shortName(w.name)}</b><small className="mono">{w.ticker}</small></span>
                <Spark values={w.quote?.spark ?? []} base={w.quote?.prev_close} width={84} height={24} />
                <span className="dash-num"><b>{money(w.quote?.last)}</b><small className={chgClass(w.quote?.chg_pct)}>{pct(w.quote?.chg_pct, 2, true)}</small></span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

const ALERT_ICON: Record<LiveAlert["kind"], [string, string]> = { below: ["arrow-down", "down"], above: ["arrow-up", "up"], buy_below: ["tag", "up"], move: ["pulse", "warn"] };

function Alerts({ alerts }: { alerts: LiveAlert[] }) {
  const rows = [...alerts].sort((a, b) => b.t - a.t).slice(0, 7);
  if (!rows.length) return <Quiet icon="bell">No alerts yet. Set price levels on a watchlist, or wait for a buy-below crossing.</Quiet>;
  return (
    <ul className="dash-rows">
      {rows.map((a) => {
        const [icon, tone] = ALERT_ICON[a.kind] ?? ["bell", ""];
        return (
          <li key={a.id}>
            <Link className={`dash-row dash-alert ${a.seen ? "" : "new"}`} to={`/watchlist?t=${encodeURIComponent(a.ticker)}`}>
              <Icon name={icon} className={`sm ${tone}`} />
              <span className="dash-co"><b className="ellipsis">{shortName(a.name)}</b><small className="ellipsis">{a.message.replace(a.name, "").trim().replace(/^is /, "")}</small></span>
              <span className="dash-t">{a.seen ? "" : <span className="dash-new">new</span>}{ago(a.t)}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function Research({ verdicts, total }: { verdicts: Ctx["verdicts"]; total: number }) {
  // the largest gaps between price and value, the agents' strongest calls first
  const ideas = verdicts.filter((v) => v.label !== "Insufficient evidence" && isNum(v.upside))
    .sort((a, b) => (b.upside ?? 0) - (a.upside ?? 0)).slice(0, 5);
  const flagged = verdicts.filter((v) => (v.red_flags?.length ?? 0) > 0).slice(0, 3);
  if (!verdicts.length) return <Quiet icon="organization">{total ? "No research on the companies in focus yet." : "No research yet. Start a run with Research."}</Quiet>;
  return (
    <div className="dash-stack">
      {ideas.length ? (
        <ul className="dash-rows">
          {ideas.map((v) => (
            <li key={v.company}>
              <Link className="dash-row" to={companyPath(v.company)}>
                <span className="dash-co"><b className="ellipsis">{shortName(v.company)}</b><small>{isNum(v.confidence) ? `confidence ${v.confidence.toFixed(0)}` : v.sector}</small></span>
                <LabelBadge label={v.label} />
                <b className={`dash-up mono ${chgClass(v.upside)}`}>{pct(v.upside, 0, true)}</b>
              </Link>
            </li>
          ))}
        </ul>
      ) : <p className="dash-note">No verdict has a value to compare with the price yet.</p>}
      {flagged.length > 0 && (
        <div className="dash-flags">
          <span className="dash-sub"><Icon name="warning" className="xs down" />Red flags</span>
          {flagged.map((v) => <Link key={v.company} to={companyPath(v.company)} className="dash-flag"><b>{shortName(v.company)}</b> {v.red_flags![0]}</Link>)}
        </div>
      )}
    </div>
  );
}

function Activity({ active, jobs, run, autostart, feed }: {
  active: import("../lib/api").JobSummary | null; jobs: import("../lib/api").JobSummary[]; run?: import("../lib/agents").RunInfo;
  autostart?: { enabled: boolean; mode: string }; feed?: { auto_feed: boolean; feed_after: string; last_auto: string | null };
}) {
  const last = jobs.find((j) => j.status !== "running" && j.status !== "queued");
  const Row = ({ k, children, to }: { k: string; children: ReactNode; to?: string }) => (
    <li>{to ? <Link className="dash-kv" to={to}><span>{k}</span><span>{children}</span></Link> : <div className="dash-kv"><span>{k}</span><span>{children}</span></div>}</li>
  );
  return (
    <ul className="dash-rows">
      <Row k="Running now" to={active ? `/operations?job=${active.id}` : "/operations"}>
        {active ? <><span className="live-dot on" />{jobTitle(active.kind, active.opts)} · {duration(Date.now() / 1000 - active.started)}</> : <span className="faint">Nothing</span>}
      </Row>
      <Row k="Last job" to={last ? `/operations?job=${last.id}` : undefined}>
        {last ? <><span className={last.status === "succeeded" ? "up" : last.status === "failed" ? "down" : "faint"}>{last.status === "succeeded" ? "Done" : last.status === "failed" ? "Failed" : last.status}</span> · {jobTitle(last.kind, last.opts)} · {ago(last.finished ?? last.started)}</> : <span className="faint">None yet</span>}
      </Row>
      <Row k="Last research" to="/agents">
        {run ? <>Run #{run.id} · {run.mode} · {run.companies} companies · {run.finished ? ago(Date.parse(run.finished) / 1000) : "did not finish"}</> : <span className="faint">None yet</span>}
      </Row>
      <Row k="Auto-start" to="/agents">{autostart ? (autostart.enabled ? `On · ${autostart.mode === "quick" ? "quick sweep" : "full research"} when the app opens` : "Off") : "…"}</Row>
      <Row k="Evening refresh" to="/performance?tab=training">{feed ? (feed.auto_feed ? `Daily after ${feed.feed_after} IST` : "Off") : "…"}</Row>
    </ul>
  );
}

function Markets({ indices, sectors, error }: { indices: IndexQuote[]; sectors: IndexQuote[]; error: boolean }) {
  if (!indices.length) return <Quiet icon="graph" loading={!error}>{error ? "Index prices are unavailable right now." : ""}</Quiet>;
  const sec = [...sectors].filter((s) => isNum(s.chg_pct)).sort((a, b) => b.chg_pct! - a.chg_pct!);
  return (
    <div className="dash-stack">
      <ul className="dash-rows">
        {indices.map((i) => (
          <li key={i.ticker}>
            <Link className="dash-row" to={`/markets?t=${encodeURIComponent(i.ticker)}`}>
              <span className="dash-co"><b className="ellipsis">{i.name}</b></span>
              <Spark values={i.spark?.length ? i.spark : i.month} base={i.prev} width={84} height={24} />
              <span className="dash-num"><b>{num(i.last, 2)}</b><small className={chgClass(i.chg_pct)}>{pct(i.chg_pct, 2, true)}</small></span>
            </Link>
          </li>
        ))}
      </ul>
      {sec.length > 0 && (
        <div className="dash-sectors" aria-label="Sector indices today">
          {sec.map((s) => (
            <span key={s.ticker} className={`dash-sector ${chgClass(s.chg_pct)}`} style={{ ["--a" as string]: `${Math.min(100, Math.abs(s.chg_pct!) * 60)}%` }}>
              {s.name}<b>{pct(s.chg_pct, 1, true)}</b>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Lists({ lists, items }: { lists: Ctx["lists"]; items: WatchItem[] }) {
  if (!lists.length) return <Quiet icon="eye">No watchlists yet.</Quiet>;
  return (
    <ul className="dash-rows">
      {lists.map((l) => {
        const mine = items.filter((w) => (w.lists ?? []).includes(l.id));
        const ch = mine.map((w) => w.quote?.chg_pct).filter(isNum) as number[];
        const avg = ch.length ? ch.reduce((a, b) => a + b, 0) / ch.length : null;
        const zone = mine.filter(inZone).length;
        return (
          <li key={l.id}>
            <Link className="dash-row" to={`/watchlist/${encodeURIComponent(l.id)}`}>
              <span className="dash-sw" style={{ background: l.color }} aria-hidden />
              <span className="dash-co"><b className="ellipsis">{l.name}</b><small>{l.count} companies · {ch.filter((v) => v > 0).length} up, {ch.filter((v) => v < 0).length} down</small></span>
              {zone > 0 && <span className="dash-tag in"><Icon name="tag" className="xs" />{zone} in buy zone</span>}
              <span className="dash-num"><b className={chgClass(avg)}>{pct(avg, 2, true)}</b><small>average today</small></span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

const board = (model?: string) => `/performance?tab=board${model ? `&model=${encodeURIComponent(model)}` : ""}`;
const TRAINING = "/performance?tab=training";

function Models({ metrics, wins, learning }: { metrics: Record<string, unknown>[]; wins: Record<string, unknown>[]; learning?: import("../lib/live").LearningStatus }) {
  const ranked = metrics.filter((r) => isNum(r["MedAPE %"])).sort((a, b) => (a["MedAPE %"] as number) - (b["MedAPE %"] as number));
  const hm = metrics.find((r) => r.Model === HM);
  const best = ranked[0];
  const trend = (learning?.history ?? []).map((h) => h.hm_medape).filter(isNum) as number[];
  const models = metrics.map((r) => String(r.Model));

  // which model came closest to the price: the five that won most, the HYBRID MODEL, the rest folded into "Other"
  const won = wins.filter((r) => isNum(r.Wins) && (r.Wins as number) > 0).sort((a, b) => (b.Wins as number) - (a.Wins as number));
  const keep = won.filter((r, i) => i < 5 || r.Model === HM);
  const rest = won.filter((r) => !keep.includes(r)).reduce((a, r) => a + (r.Wins as number), 0);
  const winSlices: Slice[] = [
    ...keep.map((r) => ({ name: String(r.Model), value: r.Wins as number, color: modelColor(String(r.Model), models), to: board(String(r.Model)) })),
    ...(rest ? [{ name: "Other models", value: rest, color: "var(--fg-3)", to: board() }] : []),
  ];
  const top = won[0];

  const hit = hm && isNum(hm["Hit +/-20%"]) ? (hm["Hit +/-20%"] as number) : null;
  const hitSlices: Slice[] = hit == null ? [] : [
    { name: "Within ±20%", value: hit, color: HM_COLOR, to: board(HM) },
    { name: "Off by more", value: 100 - hit, color: "var(--fg-3)", to: board(HM) },
  ];

  const c = learning?.cache;
  const total = c ? c.fresh + c.stale + c.missing : 0;
  const poolSlices: Slice[] = !c ? [] : [
    { name: "Fresh accounts", value: c.fresh, color: "var(--up)", to: TRAINING },
    { name: "Stale", value: c.stale, color: "var(--c-yellow)", to: TRAINING },
    { name: "Missing", value: c.missing, color: "var(--down)", to: TRAINING },
  ];

  return (
    <div className="dash-health">
      <Donut title="Closest to the price" slices={winSlices} unit="wins" empty="Run a valuation report"
        center={top ? pctUnits(top["Win rate %"], 0) : "–"} centerSub={top ? String(top.Model) : ""} />
      <Donut title="HYBRID MODEL within ±20%" slices={hitSlices} unit="%" empty="Run a valuation report"
        center={hit != null ? pctUnits(hit, 0) : "–"} centerSub="of its values" />
      <Donut title="Learning pool" slices={poolSlices} unit="companies" empty={learning ? "No companies yet" : "Loading…"}
        center={learning ? learning.companies.toLocaleString("en-IN") : "–"} centerSub={total ? `${Math.round((100 * c!.fresh) / total)}% fresh` : "companies"} />
      <ul className="dash-hstats">
        <li><Link to={board(HM)}><span className="k">HYBRID MODEL error</span><b className="hm">{hm ? pctUnits(hm["MedAPE %"], 1) : "–"}</b><small>median miss vs the 1-May price</small></Link></li>
        <li><Link to={board(best ? String(best.Model) : undefined)}><span className="k">Most accurate</span><b className="ellipsis">{best ? String(best.Model) : "–"}</b><small>{best ? `${pctUnits(best["MedAPE %"], 1)} median error` : "run a valuation report"}</small></Link></li>
        <li><Link to={TRAINING}><span className="k">Accuracy over time</span>{trend.length > 1 ? <Spark values={trend.map((v) => -v)} width={110} height={26} /> : <b>–</b>}
          <small>{trend.length > 1 ? (trend[trend.length - 1] < trend[0] ? "getting more accurate" : "not improving yet") : "needs two reports"}</small></Link></li>
      </ul>
    </div>
  );
}

interface Slice { name: string; value: number; color: string; to: string }

/** A donut whose slices and legend rows open the page behind them; the legend is the keyboard route and names every colour. */
function Donut({ title, slices, unit, center, centerSub, empty }: { title: string; slices: Slice[]; unit: string; center: ReactNode; centerSub: string; empty: string }) {
  const nav = useNavigate();
  const sum = slices.reduce((a, s) => a + s.value, 0);
  const fmt = (v: number) => (unit === "%" ? pctUnits(v, 0) : `${v.toLocaleString("en-IN")} ${unit}`);
  const share = (v: number) => (unit === "%" || !sum ? "" : pct(v / sum, 0));
  return (
    <figure className="dash-pie">
      <figcaption className="k">{title}</figcaption>
      {!sum ? <div className="dash-pie-none">{empty}</div> : (
        <div className="dash-pie-b">
          <div className="dash-pie-c">
            <PieChart width={132} height={132}>
              <Pie data={slices} dataKey="value" nameKey="name" innerRadius={44} outerRadius={64} startAngle={90} endAngle={-270}
                stroke="var(--bg)" strokeWidth={2} isAnimationActive={false} onClick={(d: { payload?: Slice }) => d.payload && nav(d.payload.to)}>
                {slices.map((s) => <Cell key={s.name} fill={s.color} />)}
              </Pie>
              {/* pinned just above the donut, on top of everything, so it never covers the ring or the centre figure */}
              <Tooltip wrapperStyle={{ zIndex: 3 }} allowEscapeViewBox={{ x: true, y: true }} position={{ x: 0, y: -40 }} content={({ active, payload }) => {
                const s = active ? (payload?.[0]?.payload as Slice | undefined) : undefined;
                return s ? <div className="tip dash-pie-tip"><div className="tr"><span className="row" style={{ gap: 6 }}><span className="sw" style={{ background: s.color }} />{s.name}</span>
                  <span className="mono strong">{fmt(s.value)}{share(s.value) && <span className="faint"> · {share(s.value)}</span>}</span></div></div> : null;
              }} />
            </PieChart>
            <div className="dash-pie-mid" aria-hidden><b>{center}</b><small className="ellipsis">{centerSub}</small></div>
          </div>
          <ul className="dash-pie-l">
            {slices.map((s) => (
              <li key={s.name}>
                <Link to={s.to}><span className="dash-sw" style={{ background: s.color }} aria-hidden /><span className="ellipsis">{s.name}</span>
                  <span className="mono">{unit === "%" ? pctUnits(s.value, 0) : s.value.toLocaleString("en-IN")}</span></Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </figure>
  );
}

function Quiet({ icon, loading, children }: { icon: string; loading?: boolean; children: ReactNode }) {
  return <div className="dash-quiet">{loading ? <><Icon name="loading" className="spin" />Loading…</> : <><Icon name={icon} />{children}</>}</div>;
}
