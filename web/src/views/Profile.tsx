import { Fragment, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useHistory, useIntel } from "../lib/hooks";
import { AnalystRow, Case, Verdict } from "../lib/api";
import { useWatchlist, WatchItem, WatchList } from "../lib/live";
import { isNum, money, pct, shortName, signed, slug, titleCase } from "../lib/format";
import { AGENT_NAME, HM_COLOR, LEAD_ICON, LEAD_SHORT, scoreColor } from "../lib/labels";
import { companyPath, findVerdict, listCompanyPath } from "../lib/company";
import { Diverge, Empty, Icon, LabelBadge, Meter, Panel, QueryView, Tip } from "../components/ui";
import { Bridge, LensContribution, RangeLegend, RateStack, ValueRange } from "../components/charts";
import { RunButton } from "../components/RunButton";
import { ModelForecasts, useOneYearView } from "../components/ModelForecasts";
import { ChartPanel } from "../components/ChartPanel";
import { LiveForecast } from "../components/LiveForecast";
import { AddToList, NoteBox, PriceAlerts } from "../components/WatchControls";
import { plainSummary } from "../lib/plainSummary";

const LIVE = { id: "live", label: "Live", icon: "pulse" };
const RESEARCH = [
  { id: "summary", label: "Summary", icon: "note" },
  { id: "valuation", label: "Valuation", icon: "symbol-operator" },
  { id: "forecast", label: "Model forecasts", icon: "graph-line" },
  { id: "drivers", label: "Drivers & risk", icon: "pulse" },
  { id: "agents", label: "Agents & evidence", icon: "organization" },
  { id: "cases", label: "Bull vs bear", icon: "law" },
  { id: "history", label: "History", icon: "history" },
];

interface Nav { crumbs: { label: string; to?: string }[]; prev?: { to: string; label: string }; next?: { to: string; label: string } }

/** /company/<name>: a researched company's full analysis, with its live view when it is on a watchlist. */
export function CompanyByName() {
  const { company = "" } = useParams();
  const name = decodeURIComponent(company);
  const q = useIntel();
  const all = useWatchlist();
  const nav = useNavigate();
  return (
    <div className="page">
      <QueryView q={q} rows={14}>
        {(d) => {
          const list = d.verdicts ?? [];
          const i = list.findIndex((x) => x.company === name);
          const v = i >= 0 ? list[i] : null;
          const w = (all.data?.items ?? []).find((x) => (v ? findVerdict([v], x) : x.name === name)) ?? null;
          if (!v && !w) return <Panel><Empty icon="search" title={`No research for “${name}”`} action={<button className="btn sec" onClick={() => nav("/watchlist")}>Back to watchlists</button>}>It is not in the latest research run or on a watchlist. Add it to a watchlist and research it from there.</Empty></Panel>;
          const home = w?.lists?.[0];
          return <CompanyPage v={v} w={w} ticker={w?.ticker ?? v?.ticker ?? null} nav={{
            crumbs: [{ label: "Watchlists", to: "/watchlist" }, ...(v ? [{ label: v.sector }] : [])],
            prev: list[i - 1] ? { to: companyPath(list[i - 1].company), label: list[i - 1].company } : undefined,
            next: list[i + 1] ? { to: companyPath(list[i + 1].company), label: list[i + 1].company } : undefined,
          }} homeList={home} />;
        }}
      </QueryView>
    </div>
  );
}

/** /watchlist/<list>/<ticker>: a watchlist company's page - live view, forecast and the full research. */
export function CompanyInList() {
  const { id = "", ticker = "" } = useParams();
  const t = decodeURIComponent(ticker);
  const q = useWatchlist(id);
  const intel = useIntel();
  return (
    <div className="page">
      <QueryView q={q} rows={14}>
        {(d) => {
          const items = d.items;
          const i = items.findIndex((x) => x.ticker === t);
          if (!d.list || i < 0) return <Panel><Empty icon="search" title={`${t} is not on this watchlist`} action={<Link className="btn sec" to={d.list ? `/watchlist/${encodeURIComponent(id)}` : "/watchlist"}>Back to the list</Link>}>It may have been taken off.</Empty></Panel>;
          const w = items[i];
          const v = findVerdict(intel.data?.verdicts, w);
          const step = (x?: WatchItem) => (x ? { to: listCompanyPath(id, x.ticker), label: x.name } : undefined);
          return <CompanyPage v={v} w={w} list={d.list} ticker={w.ticker} researchLoading={intel.isLoading}
            nav={{ crumbs: [{ label: "Watchlists", to: "/watchlist" }, { label: d.list.name, to: `/watchlist/${encodeURIComponent(id)}` }], prev: step(items[i - 1]), next: step(items[i + 1]) }} />;
        }}
      </QueryView>
    </div>
  );
}

/**
 * The section the reader is in: the last one whose top has passed the band
 * under the sticky bar - or the last section once the page cannot scroll any
 * further (a short final section never reaches that band). A click on the nav
 * wins until its smooth scroll settles.
 */
function useScrollSpy(ids: readonly string[]) {
  const [on, setOn] = useState(ids[0]);
  const pinned = useRef<{ id: string; until: number } | null>(null);
  const key = ids.join("|");
  useEffect(() => {
    const root = document.querySelector(".main");
    if (!root) return;
    const check = () => {
      if (pinned.current && performance.now() < pinned.current.until) return;
      pinned.current = null;
      const bar = root.querySelector(".profile-bar");
      const top = (bar ? bar.getBoundingClientRect().bottom : root.getBoundingClientRect().top + 76) + 44;
      let cur = ids[0];
      for (const id of ids) { const el = document.getElementById(id); if (el && el.getBoundingClientRect().top <= top) cur = id; }
      if (root.scrollHeight - root.scrollTop - root.clientHeight < 4) cur = ids[ids.length - 1];
      setOn(cur);
    };
    // six rectangle reads per scroll event: cheap enough to run directly
    root.addEventListener("scroll", check, { passive: true });
    check();
    return () => root.removeEventListener("scroll", check);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const go = (id: string) => {
    pinned.current = { id, until: performance.now() + 900 };
    setOn(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };
  return { on, go };
}

function CompanyPage({ v, w, list, ticker, nav: n, homeList, researchLoading }: { v: Verdict | null; w: WatchItem | null; list?: WatchList; ticker: string | null; nav: Nav; homeList?: string; researchLoading?: boolean }) {
  const nav = useNavigate();
  const sections = useMemo(() => [...(ticker ? [LIVE] : []), ...(v ? RESEARCH : [])], [ticker, v]);
  const { on, go } = useScrollSpy(sections.map((x) => x.id));
  // the sticky bar wraps on narrower screens: the section nav and headings sit below whatever height it has
  const bar = useRef<HTMLDivElement>(null);
  const [barH, setBarH] = useState(76);
  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBarH(el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const name = v?.company ?? w?.name ?? ticker ?? "";
  const sym = (ticker || v?.ticker || "").split(".")[0];
  // live figures when the tracker has a quote; the research run's otherwise
  const q = w?.quote;
  const price = q?.last ?? v?.price;
  const value = q?.hm?.value ?? v?.expected_value;
  const upside = q?.hm?.upside ?? v?.upside;
  const label = q?.hm?.label ?? v?.label;
  const [prevKey, nextKey] = [n.prev?.to, n.next?.to];
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (!e.altKey || (e.target as HTMLElement)?.closest("input,textarea,select,[contenteditable]")) return;
      if (e.key === "ArrowUp" && prevKey) { e.preventDefault(); nav(prevKey); }
      else if (e.key === "ArrowDown" && nextKey) { e.preventDefault(); nav(nextKey); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [prevKey, nextKey, nav]);
  return (
    <>
      <div className="profile-bar" ref={bar}>
        <div className="id">
          <div className="row xs faint" style={{ marginBottom: 2 }}>
            {n.crumbs.map((c, i) => <Fragment key={i}>{i > 0 && <Icon name="chevron-right" className="xs" />}{c.to ? <Link to={c.to}>{c.label}</Link> : <span>{c.label}</span>}</Fragment>)}
          </div>
          <h1>{shortName(name)}</h1>
          <div className="m">
            <span className="mono faint">{ticker ?? v?.ticker}</span>{label && <LabelBadge label={label} />}
            {v?.regime && <span className="tag">{titleCase(v.regime)}</span>}{isNum(v?.valuation_fy) && <span className="tag">FY{v!.valuation_fy} accounts</span>}
            {q?.chg_pct != null && <span className={`tag ${q.chg_pct >= 0 ? "up" : "down"}`}>{pct(q.chg_pct, 2, true)} today</span>}
          </div>
        </div>
        <div className="pb-figs">
          <div><div className="k">{q?.last ? "Live price" : "Price"}</div><div className="v" style={{ color: "var(--price)" }}>{money(price)}</div></div>
          <div><div className="k">HYBRID MODEL</div><div className="v" style={{ color: HM_COLOR }}>{money(value)}</div></div>
          <div><div className="k">Upside</div><div className={`v ${isNum(upside) ? (upside >= 0 ? "up" : "down") : ""}`}>{pct(upside, 1, true)}</div></div>
          <div><div className="k">Buy-below</div><div className="v">{money(q?.hm?.buy_below ?? v?.buy_below, 0)}</div></div>
          <div><div className="k">Confidence</div><div className="v">{isNum(q?.hm?.confidence ?? v?.confidence) ? (q?.hm?.confidence ?? v!.confidence)!.toFixed(0) : "—"}</div></div>
        </div>
        <div className="row">
          {v && <Link to={`/studio?company=${slug(v.company)}`} className="btn sm sec"><Icon name="beaker" className="sm" />Studio</Link>}
          {sym && <RunButton kind="agents" options={{ tickers: sym, quick: !!v }} label={v ? "Re-check" : "Research"} icon={v ? "zap" : "rocket"} secondary={!!v} small />}
          {!w && ticker && <AddToList company={{ ticker, name, sector: v?.sector }} small />}
          <button className="ibtn" disabled={!n.prev} title={n.prev ? `${n.prev.label} (Alt+↑)` : undefined} onClick={() => n.prev && nav(n.prev.to)}><Icon name="chevron-up" /></button>
          <button className="ibtn" disabled={!n.next} title={n.next ? `${n.next.label} (Alt+↓)` : undefined} onClick={() => n.next && nav(n.next.to)}><Icon name="chevron-down" /></button>
        </div>
      </div>

      <div className="profile" style={{ marginTop: 16, ["--pb-h" as string]: `${barH}px` }}>
        <aside className="profile-side">
          <nav className="anchors" aria-label="Sections">
            {sections.map((x) => <a key={x.id} href={`#${x.id}`} className={on === x.id ? "on" : ""} onClick={(e) => { e.preventDefault(); go(x.id); }}><Icon name={x.icon} className="sm" />{x.label}</a>)}
          </nav>
          {w && <Panel title="Note" meta={list ? `on “${list.name}”` : homeList ? "on your watchlists" : undefined} className="side-note" noExport>
            <NoteBox titled w={w} list={list} onRemoved={() => list && nav(`/watchlist/${encodeURIComponent(list.id)}`)} />
          </Panel>}
        </aside>
        <div className="col" style={{ gap: 28, minWidth: 0 }}>
          {ticker && (
            <Section id="live" title="Live">
              <ChartPanel ticker={ticker} watch={w} height={520} compactHead extra={w ? <PriceAlerts w={w} row /> : undefined} />
              <LiveForecast ticker={ticker} />
            </Section>
          )}
          {!v && (
            <Panel>{researchLoading ? <Empty icon="loading" title="Loading the research…" /> : (
              <Empty icon="organization" title="Not researched yet" action={sym ? <RunButton kind="agents" options={{ tickers: sym, quick: false }} label="Research this company" icon="rocket" /> : undefined}>
                The research workforce writes its valuation, plain-words summary, model forecasts, drivers, evidence and the bull and bear cases.
                Until then the live chart and the forecast above work from its prices alone.
              </Empty>)}
            </Panel>
          )}
          {v && <Research v={v} />}
        </div>
      </div>
    </>
  );
}

/** Everything the research run says about the company: the old Coverage profile. */
function Research({ v }: { v: Verdict }) {
  return (
    <>
          <Section id="summary" title="Summary">
            <PlainWords v={v} />
            <div className="grid c-32">
              <Panel title="Research note" meta={v.summary?.by === "llm" ? "Chief agent · every point cited" : "assembled from lead findings"}>
                {v.summary?.headline && <div className="prose-h">{v.summary.headline}</div>}
                <p className="prose">{v.summary?.note || "No note was written for this run."}</p>
                {v.summary?.key_points?.length > 0 && <ul className="prose" style={{ margin: "10px 0 0", paddingLeft: 18 }}>{v.summary.key_points.map((p, i) => <li key={i}>{p.text}</li>)}</ul>}
                {v.summary?.watch_next?.length > 0 && <div className="row wrap" style={{ marginTop: 12 }}><span className="label">Watch</span>{v.summary.watch_next.map((w, i) => <span key={i} className="tag">{w}</span>)}</div>}
              </Panel>
              <Panel title="Research leads" meta="−1 … +1" flush>
                <table className="dg dense">
                  <tbody>
                    {(v.leads ?? []).map((l) => (
                      <tr key={l.lead} title={l.summary}>
                        <td><span className="row"><Icon name={LEAD_ICON[l.lead] ?? "person"} className="sm" style={{ color: scoreColor(l.score) }} />{LEAD_SHORT[l.lead] ?? l.name}</span></td>
                        <td style={{ width: "40%" }}><Diverge value={l.score} width="100%" /></td>
                        <td className="r mono" style={{ color: scoreColor(l.score) }}>{signed(l.score)}</td>
                        <td className="r mono faint">{l.usable}/{l.analysts}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            </div>
            <Panel title="Where the price sits" tools={<RangeLegend />}><ValueRange r={v} /></Panel>
          </Section>

          <Section id="valuation" title="Valuation">
            <div className="grid c2">
              <Panel title="Lens contribution" meta="how far each lens pulls the blend" flush><LensContribution r={v} /></Panel>
              <Panel title="Bridge to the HYBRID MODEL value"><Bridge r={v} /></Panel>
            </div>
            {v.gate && v.gate.after < v.gate.before && (
              <div className="note inf"><Icon name="filter" /><div>Growth-credibility gate: growth made up {pct(v.gate.pvgo_share, 0)} of the cash-flow lens, above the {pct(v.gate.allowed, 0)} this company's moat supports — cut from {money(v.gate.before, 0)} to {money(v.gate.after, 0)}.</div></div>
            )}
            <Panel title="Build-up" meta="every step of the formula" flush>
              <table className="dg dense">
                <thead><tr><th>Step</th><th className="r">Value</th><th>How</th></tr></thead>
                <tbody>{(v.waterfall ?? []).map((w, i) => <tr key={i} style={w.step.startsWith("HYBRID MODEL") ? { background: "#ad80d70e" } : undefined}><td className={w.step.startsWith("HYBRID MODEL") ? "hm" : ""}>{w.step}</td><td className="r mono strong">{money(w.value, 0)}</td><td className="muted wrap">{w.note}</td></tr>)}</tbody>
              </table>
            </Panel>
          </Section>

          <Section id="forecast" title="Model forecasts"><ModelForecasts v={v} /></Section>

          <Section id="drivers" title="Drivers & risk">
            <div className="grid c3">
              <Panel title="Discount rate"><RateStack r={v} /></Panel>
              <Panel title="Growth">
                <div className="kv" style={{ marginBottom: 12 }}>
                  <span className="k">From the accounts</span><span className="v">{pct(v.growth_base, 2)}</span>
                  <span className="k">After tilts</span><span className="v info">{pct(v.growth, 2)}</span>
                  <span className="k">Terminal</span><span className="v">{pct(v.growth_terminal, 2)}</span>
                </div>
                <Terms terms={v.growth_tilts} cap={0.02} fmt={(x) => pct(x, 2, true)} />
              </Panel>
              <Panel title="Quality" meta={`× ${isNum(v.quality_multiplier) ? v.quality_multiplier.toFixed(3) : "—"}`}><Terms terms={v.quality_terms} cap={0.1} fmt={(x) => pct(x, 1, true)} /></Panel>
            </div>
            <div className="grid c3">
              <Panel title="Risk readings" meta="0 calm · 1 severe">
                <div className="col" style={{ gap: 8 }}>{Object.entries(v.risks ?? {}).map(([k, x]) => <div key={k} className="row"><span className="small muted" style={{ width: 130 }}>{titleCase(k)}</span><Meter value={isNum(x) ? 100 - x * 100 : null} width="100%" /><span className="mono xs" style={{ width: 34, textAlign: "right" }}>{isNum(x) ? x.toFixed(2) : "—"}</span></div>)}</div>
              </Panel>
              <Panel title="Red flags" meta={`${v.red_flags?.length ?? 0}`}>
                {v.red_flags?.length ? <div className="list">{v.red_flags.map((f, i) => <div key={i} className="li"><Icon name="warning" className="sm down" /><span>{f}</span></div>)}</div> : <span className="muted small row"><Icon name="pass" className="sm up" />No validated red flags</span>}
              </Panel>
              <Panel title="Scenarios">
                <div className="kv">
                  {(["bear", "base", "bull"] as const).map((k) => {
                    const val = k === "bear" ? v.bear_value : k === "bull" ? v.bull_value : v.base_value;
                    return <Fragment key={k}><span className="k">{titleCase(k)} · {pct(v.probabilities?.[k], 0)}</span><span className="v">{money(val, 0)}</span></Fragment>;
                  })}
                  <span className="k strong">Weighted</span><span className="v hm">{money(v.expected_value, 0)}</span>
                </div>
                <div className="divider" style={{ height: 1, background: "var(--line)", margin: "12px 0" }} />
                <div className="label" style={{ marginBottom: 6 }}>Confidence parts</div>
                <div className="col" style={{ gap: 6 }}>{Object.entries(v.confidence_parts ?? {}).map(([k, x]) => <div key={k} className="row"><span className="small muted" style={{ width: 120 }}>{titleCase(k)}</span><Meter value={isNum(x) ? x * 100 : null} width="100%" color="var(--c-blue)" /></div>)}</div>
              </Panel>
            </div>
          </Section>

          <Section id="agents" title="Agents & evidence"><Agents v={v} /></Section>
          <Section id="cases" title="Bull vs bear"><Cases v={v} /></Section>
          <Section id="history" title="History"><History company={v.company} /></Section>
    </>
  );
}

/** What the research and the forecasts say, in everyday words. */
function PlainWords({ v }: { v: Verdict }) {
  const year = useOneYearView(v);
  const p = plainSummary(v, year);
  return (
    <Panel title="In plain words" meta="what the analysis and the forecasts say, without the jargon" className="plain" exportTitle={`${v.company} — summary`}>
      <div className={`plain-h ${p.tone}`}><Icon name={p.tone === "up" ? "arrow-up" : p.tone === "down" ? "warning" : p.tone === "warn" ? "arrow-down" : "dash"} />{p.headline}</div>
      <p className="plain-p">{p.paragraph}</p>
      {(p.good.length > 0 || p.watch.length > 0) && (
        <div className="plain-lists">
          {p.good.length > 0 && <div><div className="label">In its favour</div><ul>{p.good.map((x, i) => <li key={i} className="g"><Icon name="pass" className="xs" />{x}</li>)}</ul></div>}
          {p.watch.length > 0 && <div><div className="label">Keep an eye on</div><ul>{p.watch.map((x, i) => <li key={i} className="w"><Icon name="eye" className="xs" />{x}</li>)}</ul></div>}
        </div>
      )}
      <div className="xs faint" style={{ marginTop: 10 }}>A reading of the models and the research agents, not investment advice.</div>
    </Panel>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return <section id={id} className="section"><h2>{title}</h2>{children}</section>;
}

function Terms({ terms, cap, fmt }: { terms: Record<string, number>; cap: number; fmt: (x: number) => string }) {
  const e = Object.entries(terms ?? {});
  if (!e.length) return <p className="muted small">None applied.</p>;
  return <div className="col" style={{ gap: 8 }}>{e.map(([k, x]) => <div key={k} className="row"><span className="small muted" style={{ width: 130 }}>{titleCase(k)}</span><Diverge value={x} max={cap} width="100%" /><span className={`mono xs ${x > 0 ? "up" : x < 0 ? "down" : "faint"}`} style={{ width: 56, textAlign: "right" }}>{fmt(x)}</span></div>)}</div>;
}

function Agents({ v }: { v: Verdict }) {
  const [open, setOpen] = useState<string | null>(null);
  const rows = useMemo(() => [...(v.analysts ?? [])].sort((a, b) => a.lead.localeCompare(b.lead)), [v.analysts]);
  return (
    <Panel flush>
      <table className="dg">
        <thead><tr><th style={{ width: 28 }} /><th>Analyst</th><th>Lead</th><th>Finding</th><th>Status</th><th style={{ width: 90 }}>Score</th><th className="r">Conf.</th></tr></thead>
        <tbody>
          {rows.map((a: AnalystRow) => (
            <Fragment key={a.agent}>
              <tr className="click" onClick={() => setOpen(open === a.agent ? null : a.agent)}>
                <td><Icon name={open === a.agent ? "chevron-down" : "chevron-right"} className="sm faint" /></td>
                <td className="strong">{AGENT_NAME[a.agent] ?? titleCase(a.agent)}</td>
                <td className="muted">{LEAD_SHORT[a.lead] ?? a.lead}</td>
                <td className="muted ellipsis" style={{ maxWidth: "min(420px, 30vw)" }}>{a.summary}</td>
                <td><span className="row" style={{ gap: 4 }}>
                  {a.used_llm && <span className="tag hm">AI</span>}
                  {a.status !== "ok" ? <span className="tag" style={{ color: a.status === "error" ? "var(--down)" : "var(--c-yellow)" }}>{a.status === "error" ? "error" : "no data"}</span> : a.validated === false ? <span className="tag warn">unvalidated</span> : <span className="tag up">ok</span>}
                  {a.flags?.length > 0 && <span className="tag down">{a.flags.length} flag</span>}
                </span></td>
                <td><Diverge value={a.score} width={80} /></td>
                <td className="r mono">{pct(a.confidence, 0)}</td>
              </tr>
              {open === a.agent && (
                <tr className="analyst-row"><td /><td colSpan={6} style={{ whiteSpace: "normal", padding: "10px 12px 14px" }}>
                  <p className="prose" style={{ marginBottom: 8 }}>{a.summary}</p>
                  {a.flags?.map((f, i) => <div key={i} className="li"><Icon name="warning" className="sm down" /><span>{f}</span></div>)}
                  {a.notes?.map((n, i) => <div key={i} className="li muted"><Icon name="info" className="sm" /><span>{n}</span></div>)}
                  <div className="label" style={{ marginTop: 8 }}>Evidence</div>
                  {a.evidence?.length ? <ul className="ev-list">{a.evidence.map((e) => <li key={e.id}><span className="faint mono">{e.id}</span><span className="muted">{e.source}</span>{e.url ? <a href={e.url} target="_blank" rel="noreferrer noopener">{e.title}</a> : <span>{e.title}</span>}{e.date && <span className="faint">{e.date}</span>}</li>)}</ul> : <span className="muted small">None attached.</span>}
                </td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function Cases({ v }: { v: Verdict }) {
  const side = (c: Case | null, kind: "bull" | "bear") => (
    <Panel title={kind === "bull" ? "The case for" : "The case against"} meta={kind === "bull" ? `bull ${pct(v.probabilities?.bull, 0)} · ${money(v.bull_value, 0)}` : `bear ${pct(v.probabilities?.bear, 0)} · ${money(v.bear_value, 0)}`}>
      {!c ? <p className="muted small">Not written in this run.</p> : (
        <div className={`case ${kind}`}>
          <p className="prose">{c.thesis}</p>
          {c.claims?.length > 0 && <ul>{c.claims.map((x, i) => <li key={i}>{x.text}</li>)}</ul>}
          {c.invalidated_if && <p className="muted small" style={{ marginTop: 10 }}><b className="strong">Wrong if:</b> {c.invalidated_if}</p>}
        </div>
      )}
    </Panel>
  );
  return <div className="grid c2">{side(v.bull_case, "bull")}{side(v.bear_case, "bear")}</div>;
}

function History({ company }: { company: string }) {
  const q = useHistory(company);
  return (
    <Panel title="HYBRID MODEL value and price across research runs">
      <QueryView q={q}>
        {(rows) => rows.length < 2 ? <Empty icon="history" title="Not enough history yet">Each research run adds a point.</Empty> : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={rows.map((r) => ({ ...r, when: r.date?.slice(5, 16).replace("T", " ") }))} margin={{ top: 8, right: 16, bottom: 0, left: 4 }}>
              <CartesianGrid strokeDasharray="2 4" />
              <XAxis dataKey="when" tickLine={false} axisLine={{ stroke: "var(--line)" }} minTickGap={24} />
              <YAxis tickLine={false} axisLine={false} width={70} tickFormatter={(x) => money(x, 0)} />
              <Tooltip content={<Tip fmt={(x) => money(x)} />} />
              <Legend iconType="plainline" />
              <Line type="monotone" dataKey="value" name="HYBRID MODEL" stroke={HM_COLOR} strokeWidth={2.5} dot={{ r: 2 }} connectNulls />
              <Line type="monotone" dataKey="price" name="Price" stroke="#E0B97F" strokeWidth={2} dot={{ r: 2 }} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        )}
      </QueryView>
    </Panel>
  );
}
