import { ReactNode, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { isOpen, LiveHM, ScanRow, useIndices, useLiveAlerts, useLiveSearch, useQuickForecasts, useScan, useWatchlist, useWatchMutations } from "../lib/live";
import { ago, isNum, money, num, pct, shortName } from "../lib/format";
import { HM_COLOR, LABEL_HEX } from "../lib/labels";
import { ErrorNote, Icon, LabelBadge, PageHeader, Popover } from "../components/ui";
import { Column, DataGrid, GridTools, useGridState } from "../components/DataGrid";
import { ChartPanel } from "../components/ChartPanel";
import { Position, Spark } from "../components/Spark";
import { useApp } from "../components/workbenchContext";
import { Select } from "../components/Select";
import { listCompanyPath } from "../lib/company";

type Preset = "all" | "gainers" | "losers" | "active" | "volume" | "high52" | "low52" | "oversold" | "value";
const PRESETS: { id: Preset; label: string; icon: string; hint: string }[] = [
  { id: "all", label: "All", icon: "list-flat", hint: "Every company, by turnover" },
  { id: "gainers", label: "Top gainers", icon: "arrow-up", hint: "Biggest rise in the last session" },
  { id: "losers", label: "Top losers", icon: "arrow-down", hint: "Biggest fall in the last session" },
  { id: "active", label: "Most active", icon: "flame", hint: "Highest turnover (price × volume)" },
  { id: "volume", label: "Volume spikes", icon: "pulse", hint: "Volume at least 2× its 20-day average" },
  { id: "high52", label: "Near 52W high", icon: "triangle-up", hint: "Within 3% of the 52-week high" },
  { id: "low52", label: "Near 52W low", icon: "triangle-down", hint: "Within 5% of the 52-week low" },
  { id: "oversold", label: "RSI extremes", icon: "dashboard", hint: "RSI(14) below 30 or above 70" },
  { id: "value", label: "Below buy-below", icon: "tag", hint: "Covered companies trading under the HYBRID MODEL buy-below price" },
];
const LISTS = [["", "All lists"], ["coverage", "My coverage"], ["training", "Training list"], ["watchlist", "Watchlist"]] as const;

function presetRows(rows: ScanRow[], p: Preset): ScanRow[] {
  const by = (f: (r: ScanRow) => number | null | undefined, desc = true) =>
    [...rows].filter((r) => isNum(f(r))).sort((a, b) => (desc ? (f(b)! - f(a)!) : (f(a)! - f(b)!)));
  switch (p) {
    case "gainers": return by((r) => r.chg_pct).filter((r) => (r.chg_pct ?? 0) > 0);
    case "losers": return by((r) => r.chg_pct, false).filter((r) => (r.chg_pct ?? 0) < 0);
    case "active": return by((r) => r.turnover);
    case "volume": return by((r) => r.vol_ratio).filter((r) => (r.vol_ratio ?? 0) >= 2);
    case "high52": return by((r) => r.from_hi).filter((r) => (r.from_hi ?? -1) >= -0.03);
    case "low52": return by((r) => r.from_lo, false).filter((r) => (r.from_lo ?? 1) <= 0.05);
    case "oversold": return by((r) => r.rsi, false).filter((r) => (r.rsi ?? 50) < 30 || (r.rsi ?? 50) > 70);
    case "value": return by((r) => r.hm?.upside).filter((r) => r.hm?.buy_below && r.last <= r.hm.buy_below);
    default: return by((r) => r.turnover);
  }
}

const EXPORT_TITLE = "Market scanner";

export function Markets() {
  const [params, setParams] = useSearchParams();
  const ticker = params.get("t") || "^NSEI";
  const open = (t: string) => { const p = new URLSearchParams(params); p.set("t", t); setParams(p, { replace: true }); };
  const ix = useIndices();
  const market = ix.data?.market;
  const chartRef = useRef<HTMLDivElement>(null);
  // the chart sits above the scanner: bring it back when a row is picked further down
  const reveal = () => { const r = chartRef.current?.getBoundingClientRect(); if (r && r.top < 0) chartRef.current!.scrollIntoView({ behavior: "smooth", block: "start" }); };

  return (
    <div className="page">
      <PageHeader crumbs={[{ label: "Analysis" }, { label: "Markets" }]} title="Markets"
        sub={market ? <span className="row" style={{ gap: 8 }}><span className={`live-dot ${isOpen(market) ? "on" : ""}`}>{isOpen(market) ? (market.state === "pre-open" ? "Pre-open" : "Market open") : "Market closed"}</span><span>{market.ist}</span><span className="faint">· {market.delay_note}</span></span> : "Live NSE prices, a market-wide scanner and charts for any listed company."}
        actions={<TickerSearch onPick={open} />} />
      <Radar selected={ticker} onPick={(t) => { open(t); reveal(); }} />
      <div className="mkt">
        <div ref={chartRef}><ChartPanel ticker={ticker} height={560} /></div>
        <Scanner selected={ticker} onPick={(t) => { open(t); reveal(); }} />
      </div>
    </div>
  );
}

interface RadarRow { ticker: string; name: string; last: number | null; chg: number | null; hm?: LiveHM | null; vol?: number | null; list?: string }

/**
 * What deserves a look right now, refreshed with every price update: who has
 * just dropped into the HYBRID MODEL buy zone, the biggest gaps to value, what
 * the live forecast leans towards for today, and today's unusual moves.
 * Tracked (watchlist) prices win over the scanner's, being fresher.
 */
function Radar({ selected, onPick }: { selected: string; onPick: (t: string) => void }) {
  const scan = useScan();
  const wl = useWatchlist();
  const fc = useQuickForecasts();
  const alerts = useLiveAlerts();
  const rows = useMemo(() => {
    const by = new Map<string, RadarRow>();
    for (const r of scan.data?.rows ?? []) by.set(r.ticker, { ticker: r.ticker, name: r.name, last: r.last, chg: r.chg_pct, hm: r.hm, vol: r.vol_ratio });
    for (const w of wl.data?.items ?? []) {
      const q = w.quote;
      if (!q?.last) continue;
      const old = by.get(w.ticker);
      by.set(w.ticker, { ticker: w.ticker, name: w.name, last: q.last, chg: q.chg_pct ?? null, hm: q.hm ?? old?.hm, vol: old?.vol, list: w.lists?.[0] });
    }
    return [...by.values()];
  }, [scan.data, wl.data]);
  const buyZone = rows.filter((r) => r.hm?.buy_below && isNum(r.last) && r.last <= r.hm.buy_below).sort((a, b) => a.last! / a.hm!.buy_below! - b.last! / b.hm!.buy_below!);
  const gaps = rows.filter((r) => isNum(r.hm?.upside) && r.hm!.upside! > 0).sort((a, b) => b.hm!.upside! - a.hm!.upside!);
  const outlook = rows.filter((r) => fc.data?.[r.ticker]).sort((a, b) => Math.abs(fc.data![b.ticker]["1d"].p_up - 0.5) - Math.abs(fc.data![a.ticker]["1d"].p_up - 0.5));
  const today = new Date().toISOString().slice(0, 10);
  const fired = new Map<string, number>();
  for (const al of alerts.data ?? []) if (new Date(al.t * 1000).toISOString().slice(0, 10) === today) fired.set(al.ticker, (fired.get(al.ticker) ?? 0) + 1);
  const unusual = rows.filter((r) => (r.vol ?? 0) >= 2 || Math.abs(r.chg ?? 0) >= 0.04 || fired.has(r.ticker))
    .sort((a, b) => (b.vol ?? 1) * Math.abs(b.chg ?? 0) + (fired.get(b.ticker) ?? 0) - ((a.vol ?? 1) * Math.abs(a.chg ?? 0) + (fired.get(a.ticker) ?? 0)));
  const loading = !scan.data && !wl.data;
  const item = (r: RadarRow, right: ReactNode, sub: ReactNode) => (
    <div key={r.ticker} className={`rd-row ${selected === r.ticker ? "on" : ""}`} role="button" tabIndex={0} onClick={() => onPick(r.ticker)} onKeyDown={(e) => e.key === "Enter" && onPick(r.ticker)}>
      <div className="rd-n"><b className="ellipsis">{shortName(r.name)}</b><small className="ellipsis">{sub}</small></div>
      <div className="rd-v">{right}</div>
      {r.list && <Link className="ibtn sm rd-open" to={listCompanyPath(r.list, r.ticker)} onClick={(e) => e.stopPropagation()} title="Full analysis"><Icon name="go-to-file" className="xs" /></Link>}
    </div>
  );
  const chg = (r: RadarRow) => <span className={`mono xs ${(r.chg ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.chg, 1, true)}</span>;
  const cols: { t: string; icon: string; hint: string; rows: RadarRow[]; empty: string; render: (r: RadarRow) => ReactNode }[] = [
    { t: "In the buy zone", icon: "tag", hint: "trading under the HYBRID MODEL buy-below price", rows: buyZone, empty: "No valued company is under its buy-below price.",
      render: (r) => item(r, <><b className="mono up">{pct(r.last! / r.hm!.buy_below! - 1, 1, true)}</b>{chg(r)}</>, <>under buy-below {money(r.hm!.buy_below, 0)}</>) },
    { t: "Biggest gap to value", icon: "symbol-operator", hint: "live price furthest below the HYBRID MODEL value", rows: gaps, empty: "Value companies (a valuation report or research run) to see their gaps.",
      render: (r) => item(r, <><b className="mono up">{pct(r.hm!.upside, 0, true)}</b>{chg(r)}</>, <>{money(r.last)} → <span style={{ color: HM_COLOR }}>{money(r.hm!.value, 0)}</span></>) },
    { t: "Today's lean", icon: "graph-line", hint: "live forecast for the rest of the day, tracked companies", rows: outlook, empty: "Track companies on a watchlist for live forecasts.",
      render: (r) => { const f = fc.data![r.ticker]; const up = f["1d"].p_up >= 0.5; return item(r, <><b className={`mono ${up ? "up" : "down"}`}>{Math.round((up ? f["1d"].p_up : 1 - f["1d"].p_up) * 100)}% {up ? "up" : "down"}</b><span className="mono xs faint">1 hr {pct(f["1h"].change, 2, true)}</span></>, <>today {money(f["1d"].low, 0)}–{money(f["1d"].high, 0)}</>); } },
    { t: "Unusual today", icon: "pulse", hint: "volume spikes, moves over 4% and alerts that fired", rows: unusual, empty: "Nothing unusual so far today.",
      render: (r) => item(r, <>{chg(r)}{isNum(r.vol) && r.vol >= 2 ? <span className="mono xs warn">{r.vol.toFixed(1)}× vol</span> : fired.has(r.ticker) ? <span className="xs warn">{fired.get(r.ticker)} alert{fired.get(r.ticker)! > 1 ? "s" : ""}</span> : null}</>, <>{money(r.last)}</>) },
  ];
  return (
    <section className="panel radar">
      <div className="panel-h"><h3>Research radar</h3><span className="meta">what deserves a look right now · refreshed with every price update · click one for its chart</span></div>
      <div className="rd-cols">
        {cols.map((c) => (
          <div key={c.t} className="rd-col">
            <div className="rd-h"><Icon name={c.icon} className="sm" /><b>{c.t}</b><span className="n">{c.rows.length}</span></div>
            <div className="xs faint rd-hint">{c.hint}</div>
            {loading ? <div className="xs faint rd-empty">Loading…</div> : c.rows.length ? c.rows.slice(0, 6).map(c.render) : <div className="xs faint rd-empty">{c.empty}</div>}
          </div>
        ))}
      </div>
    </section>
  );
}

function TickerSearch({ onPick }: { onPick: (t: string) => void }) {
  const [text, setText] = useState("");
  const s = useLiveSearch(text);
  return (
    <Popover className="pop" trigger={(open, toggle) => (
      <button className={`btn sec ${open ? "on" : ""}`} onClick={toggle}><Icon name="search" className="sm" />Look up a company</button>
    )}>
      {(close) => (
        <div style={{ width: 360 }}>
          <div className="search" style={{ margin: 10 }}><Icon name="search" /><input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="Name or NSE symbol, e.g. TCS"
            onKeyDown={(e) => { if (e.key === "Enter" && s.data?.[0]) { onPick(s.data[0].ticker); close(); } }} /></div>
          <div className="feed" style={{ maxHeight: 320 }}>
            {(s.data ?? []).map((m) => (
              <div key={m.ticker} className="ev" onClick={() => { onPick(m.ticker); close(); }}>
                <span className="ic"><Icon name={m.lookup ? "globe" : "symbol-class"} className="sm" /></span>
                <div><div className="t">{m.lookup ? `Look up ${m.ticker} on Yahoo` : shortName(m.name)}</div><div className="d mono">{m.lookup ? "any NSE (.NS) or BSE (.BO) symbol" : `${m.ticker} · ${m.sector || "—"}`}</div></div>
              </div>
            ))}
            {text && s.data && !s.data.length && <div className="empty" style={{ padding: 20 }}><span className="small">Nothing matches.</span></div>}
          </div>
        </div>
      )}
    </Popover>
  );
}

function Scanner({ selected, onPick }: { selected: string; onPick: (t: string) => void }) {
  const q = useScan();
  const wl = useWatchlist();
  const m = useWatchMutations();
  const app = useApp();
  const [preset, setPreset] = useState<Preset>(() => { try { return (localStorage.getItem("scan.preset") as Preset) || "gainers"; } catch { return "gainers"; } });
  const [list, setList] = useState("");
  const [sector, setSector] = useState("");
  const [text, setText] = useState("");
  // a preset brings its own order back, even after a header was clicked
  const choose = (p: Preset) => { setPreset(p); state.setSort(null); try { localStorage.setItem("scan.preset", p); } catch { /* ignore */ } };
  const tracked = useMemo(() => new Set((wl.data?.items ?? []).map((w) => w.ticker)), [wl.data]);
  const all = q.data?.rows ?? [];
  const sectors = useMemo(() => [...new Set(all.map((r) => r.sector).filter(Boolean))].sort(), [all]);
  const base = useMemo(() => {
    const t = text.trim().toLowerCase();
    return all.filter((r) => (!list || r.lists.includes(list) || (list === "watchlist" && tracked.has(r.ticker)))
      && (!sector || r.sector === sector) && (!t || r.name.toLowerCase().includes(t) || r.ticker.toLowerCase().includes(t)));
  }, [all, list, sector, text, tracked]);
  const rows = useMemo(() => presetRows(base, preset), [base, preset]);
  const counts = useMemo(() => Object.fromEntries(PRESETS.map((p) => [p.id, presetRows(base, p.id).length])), [base]);
  const breadth = useMemo(() => ({ up: all.filter((r) => (r.chg_pct ?? 0) > 0).length, down: all.filter((r) => (r.chg_pct ?? 0) < 0).length }), [all]);

  const star = (r: ScanRow) => {
    const on = tracked.has(r.ticker);
    return (
      <button className={`ibtn sm ${on ? "on" : ""}`} title={on ? "Tracked — click to stop" : "Track live"} onClick={(e) => {
        e.stopPropagation();
        if (on) m.remove.mutate(r.ticker);
        else m.add.mutate({ ticker: r.ticker, name: r.name, sector: r.sector, cap: r.cap }, { onSuccess: () => app.toast(`Tracking ${shortName(r.name)}`, "ok"), onError: (er) => app.toast(String(er instanceof Error ? er.message : er), "error") });
      }}><Icon name={on ? "star-full" : "star-empty"} className="sm" style={on ? { color: "var(--c-yellow)" } : undefined} /></button>
    );
  };
  const columns: Column<ScanRow>[] = [
    { key: "star", header: "", fixed: true, width: 30, render: star },
    { key: "company", header: "Company", sticky: true, fixed: true, sort: (r) => r.name, render: (r) => <div className="co"><b>{shortName(r.name)}</b><small>{r.ticker}{r.lists.includes("coverage") ? " · covered" : ""}</small></div> },
    { key: "spark", header: "3 months", render: (r) => <Spark values={r.spark} width={84} height={24} /> },
    { key: "last", header: "Last", align: "r", sort: (r) => r.last, render: (r) => <span className="mono">{num(r.last)}</span> },
    { key: "chg", header: "Change", align: "r", sort: (r) => r.chg_pct, exportValue: (r) => pct(r.chg_pct, 2, true), render: (r) => <span className={`mono ${(r.chg_pct ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.chg_pct, 2, true)}</span> },
    { key: "vol", header: "Vol × avg", align: "r", sort: (r) => r.vol_ratio, exportValue: (r) => (isNum(r.vol_ratio) ? r.vol_ratio.toFixed(1) + "x" : ""), render: (r) => <span className={`mono ${(r.vol_ratio ?? 0) >= 2 ? "warn" : "muted"}`}>{isNum(r.vol_ratio) ? r.vol_ratio.toFixed(1) + "×" : "—"}</span> },
    { key: "turnover", header: "Turnover", align: "r", sort: (r) => r.turnover, exportValue: (r) => (isNum(r.turnover) ? (r.turnover / 1e7).toFixed(0) + " Cr" : ""), render: (r) => <span className="mono muted">{isNum(r.turnover) ? "₹" + (r.turnover / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 0 }) + " Cr" : "—"}</span> },
    { key: "w52", header: "52-week range", sort: (r) => r.from_hi, exportValue: (r) => pct(r.from_hi, 1, true) + " from high", render: (r) => <Position lo={r.lo_52} hi={r.hi_52} value={r.last} width={80} /> },
    { key: "rsi", header: "RSI", align: "r", sort: (r) => r.rsi, render: (r) => <span className={`mono ${(r.rsi ?? 50) < 30 ? "up" : (r.rsi ?? 50) > 70 ? "down" : "muted"}`}>{isNum(r.rsi) ? r.rsi.toFixed(0) : "—"}</span> },
    { key: "r1m", header: "1M", align: "r", sort: (r) => r.ret_1m, exportValue: (r) => pct(r.ret_1m, 1, true), render: (r) => <span className={`mono ${(r.ret_1m ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.ret_1m, 1, true)}</span> },
    { key: "r3m", header: "3M", align: "r", visible: false, sort: (r) => r.ret_3m, exportValue: (r) => pct(r.ret_3m, 1, true), render: (r) => <span className={`mono ${(r.ret_3m ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.ret_3m, 1, true)}</span> },
    { key: "r1y", header: "1Y", align: "r", sort: (r) => r.ret_1y, exportValue: (r) => pct(r.ret_1y, 1, true), render: (r) => <span className={`mono ${(r.ret_1y ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.ret_1y, 1, true)}</span> },
    { key: "hm", header: "HYBRID MODEL", align: "r", sort: (r) => r.hm?.value, render: (r) => r.hm ? <span className="mono" style={{ color: HM_COLOR }}>{money(r.hm.value, 0)}</span> : <span className="faint">—</span> },
    { key: "up", header: "Live upside", align: "r", sort: (r) => r.hm?.upside, exportValue: (r) => pct(r.hm?.upside, 1, true), render: (r) => r.hm ? <span className={`mono ${(r.hm.upside ?? 0) >= 0 ? "up" : "down"}`}>{pct(r.hm.upside, 1, true)}</span> : <span className="faint">—</span> },
    { key: "label", header: "Label", visible: false, sort: (r) => r.hm?.label ?? "", render: (r) => r.hm ? <LabelBadge label={r.hm.label} /> : <span className="faint">—</span> },
    { key: "sector", header: "Sector", visible: false, sort: (r) => r.sector, render: (r) => <span className="muted">{r.sector || "—"}</span> },
  ];
  const state = useGridState<ScanRow>("scan", columns);

  return (
    <section className="panel scan">
      <div className="panel-h">
        <h3>Market scanner</h3>
        <span className="meta">{all.length ? `${all.length} companies · ${breadth.up} up · ${breadth.down} down` : ""}</span>
        <div className="tools">
          {q.data?.scanning ? <span className="xs faint row"><Icon name="loading" className="xs spin" />scanning…</span>
            : <span className="xs faint" title={q.data?.seconds ? `last scan took ${q.data.seconds}s` : ""}>{q.data?.as_of ? `as of ${ago(q.data.as_of)}` : ""}</span>}
          <button className="ibtn" title="Scan again" onClick={() => fetch("/api/live/scan?refresh=true").then(() => q.refetch())}><Icon name="refresh" /></button>
          <GridTools columns={columns} state={state} exportRows={rows} exportTitle={EXPORT_TITLE} />
        </div>
      </div>
      <div className="presets">
        {PRESETS.map((p) => (
          <button key={p.id} className={`pre ${preset === p.id ? "on" : ""}`} onClick={() => choose(p.id)} title={p.hint}>
            <Icon name={p.icon} className="xs" />{p.label}<span className="n">{counts[p.id] ?? 0}</span>
          </button>
        ))}
      </div>
      <div className="toolbar">
        <div className="search" style={{ width: 200 }}><Icon name="search" /><input value={text} onChange={(e) => setText(e.target.value)} placeholder="Filter" /></div>
        <Select size="sm" value={list} onChange={setList} ariaLabel="Which companies" options={LISTS.map(([v, l]) => ({ value: v, label: l }))} />
        <Select size="sm" value={sector} onChange={setSector} style={{ maxWidth: 220 }} ariaLabel="Sector" options={[{ value: "", label: "All sectors" }, ...sectors.map((s) => ({ value: s, label: s }))]} />
        <span className="spacer" />
        <span className="xs faint">{PRESETS.find((p) => p.id === preset)?.hint} · {rows.length}</span>
      </div>
      {q.isError && <div style={{ padding: 12 }}><ErrorNote error={q.error} onRetry={() => q.refetch()} /></div>}
      {q.data?.error && <div className="note err" style={{ margin: 12 }}><Icon name="error" /><div>Last scan failed: {q.data.error}</div></div>}
      {!all.length ? (
        <div className="empty" style={{ padding: 40 }}><Icon name="loading" className="spin" /><span className="small">Scanning {">"}400 NSE companies — about 10 seconds…</span></div>
      ) : (
        <DataGrid rows={rows} columns={columns} rowKey={(r) => r.ticker} state={state} selected={selected} onSelect={onPick} onOpen={onPick}
          empty="Nothing in this scan matches." maxHeight="calc(100vh - 380px)" />
      )}
      <div className="scan-foot xs faint">
        <span className="row" style={{ gap: 6 }}><span className="sw" style={{ background: LABEL_HEX["Undervalued"] }} />Live upside = HYBRID MODEL value ÷ last price − 1, for the companies you value.</span>
      </div>
    </section>
  );
}
