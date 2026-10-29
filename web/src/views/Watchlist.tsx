import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useIntel } from "../lib/hooks";
import { Verdict } from "../lib/api";
import { findVerdict, listCompanyPath } from "../lib/company";
import { isOpen, TrackerState, useLiveAlerts, useWatchlist, useWatchlistMutations, useWatchlists, useWatchMutations, WatchItem, WatchList } from "../lib/live";
import { useScope } from "../lib/scope";
import { ResearchLauncher } from "../components/ResearchLauncher";
import { CompanyImporter, Entry } from "../components/CompanyImporter";
import { ago, isNum, money, num, pct, shortName, signed, when } from "../lib/format";
import { HM_COLOR, LABELS } from "../lib/labels";
import { Diverge, Drawer, Empty, ErrorNote, Icon, LabelBadge, Meter, PageHeader, Panel, Popover, QueryView, Toggle } from "../components/ui";
import { Column, DataGrid, GridTools, sortRows, useGridState } from "../components/DataGrid";
import { ChartPanel } from "../components/ChartPanel";
import { Position, Spark } from "../components/Spark";
import { useApp } from "../components/workbenchContext";
import { chime } from "../lib/notify";
import { ActionMenu } from "../components/Select";
import { LiveForecast } from "../components/LiveForecast";
import { WatchControls } from "../components/WatchControls";


/** One watchlist from the library, opened: its companies live, with charts, alerts and notes. */
export function WatchlistDetail() {
  const { id = "" } = useParams();
  const q = useWatchlist(id);
  const lib = useWatchlists();
  const [params, setParams] = useSearchParams();
  const sel = params.get("t");
  const pick = (t: string | null) => { const p = new URLSearchParams(params); if (t) p.set("t", t); else p.delete("t"); setParams(p, { replace: true }); };
  if (q.isError && /404|no watchlist/i.test(String((q.error as Error)?.message))) {
    return <div className="page"><Panel><Empty icon="library" title="This watchlist no longer exists" action={<Link className="btn sec" to="/watchlist">All watchlists</Link>}>It may have been deleted or renamed.</Empty></Panel></div>;
  }
  return (
    <div className="page">
      <QueryView q={q} rows={10}>
        {(d) => d.list ? <Board items={d.items} tracker={d.tracker} list={d.list} max={lib.data?.max_tracked ?? 100} tracked={lib.data?.tracked ?? d.items.length} sel={sel} pick={pick} /> : null}
      </QueryView>
    </div>
  );
}

function Board({ items, tracker, list, max, tracked, sel, pick }: { items: WatchItem[]; tracker: TrackerState; list: WatchList; max: number; tracked: number; sel: string | null; pick: (t: string | null) => void }) {
  // "Edit list" edits the name, notes and colour in place; companies are picked with the checkboxes below
  const [params, setParams] = useSearchParams();
  const editing = params.get("edit") === "1";
  const setEditing = (on: boolean) => { const p = new URLSearchParams(params); if (on) p.set("edit", "1"); else p.delete("edit"); setParams(p, { replace: true }); };
  const [checked, setChecked] = useState<Set<string>>(new Set());
  useEffect(() => setChecked(new Set()), [list.id]);
  // drop picks for companies that have left the list
  useEffect(() => setChecked((c) => { const keep = new Set([...c].filter((t) => items.some((w) => w.ticker === t))); return keep.size === c.size ? c : keep; }), [items]);
  const scope = useScope();
  const [view, setView] = useState<"tiles" | "table">(() => { try { return (localStorage.getItem("wl.view") as "tiles" | "table") || "tiles"; } catch { return "tiles"; } });
  // one sort for both views: set by the table's column headers, or the column buttons above the tiles
  const sortState = useGridState<WatchRow>("watch", WATCH_COLUMNS, { key: "chg", asc: false });
  useEffect(() => { try { localStorage.setItem("wl.view", view); } catch { /* ignore */ } }, [view]);
  const m = useWatchMutations();
  const [adding, setAdding] = useState(false);
  const [tracking, setTracking] = useState(false);
  const alerts = useLiveAlerts();
  const open = isOpen(tracker.market);
  const current = (items.find((w) => w.ticker === sel) ?? null) as WatchItem | null;

  const nav = useNavigate();
  const intel = useIntel();
  // each company with its research verdict, when the research workforce has covered it
  const rows = useMemo<WatchRow[]>(() => items.map((w) => ({ ...w, v: findVerdict(intel.data?.verdicts, w) })), [items, intel.data]);
  const [find, setFind] = useState("");
  const shown = useMemo(() => {
    const f = find.trim().toLowerCase();
    return f ? rows.filter((w) => `${w.name} ${w.ticker} ${w.sector} ${w.v?.label ?? w.quote?.hm?.label ?? ""}`.toLowerCase().includes(f)) : rows;
  }, [rows, find]);
  const sorted = useMemo(() => sortRows(shown, WATCH_COLUMNS, sortState.sort), [shown, sortState.sort]);
  const openFull = (t: string) => nav(listCompanyPath(list.id, t));

  const q = items.map((w) => w.quote).filter((x) => x && isNum(x.chg_pct));
  const today = new Date().toISOString().slice(0, 10);
  const band = [
    { k: "Companies", v: String(items.length), s: `${tracked} of ${max} tracked across every list · ${tracker.stored_bars?.toLocaleString("en-IN") ?? 0} minute bars` },
    { k: "Advancing / declining", v: `${q.filter((x) => x!.chg_pct! > 0).length} / ${q.filter((x) => x!.chg_pct! < 0).length}`, s: "last session" },
    { k: "Average change", v: q.length ? pct(q.reduce((a, x) => a + x!.chg_pct!, 0) / q.length, 2, true) : "—", s: "equal-weighted" },
    { k: "Below buy-below", v: String(items.filter((w) => w.quote?.hm?.buy_below && (w.quote.last ?? Infinity) <= w.quote.hm.buy_below).length), s: "HYBRID MODEL at the live price" },
    { k: "Alerts", v: String((alerts.data ?? []).filter((a) => new Date(a.t * 1000).toISOString().slice(0, 10) === today).length), s: "today" },
  ];

  return (
    <>
      <PageHeader crumbs={[{ label: "Analysis" }, { label: "Watchlists", to: "/watchlist" }, { label: list.name }]}
        title={<span className="row" style={{ gap: 10 }}><i className="wl-sw" style={{ background: list.color }} />{list.name}</span>}
        sub={<span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          {list.description && <span className="wl-desc">{list.description}</span>}
          <span className={`live-dot ${open && !tracker.paused ? "on" : ""}`}>{tracker.paused ? "Tracking paused" : open ? "Tracking live" : "Market closed"}</span>
          <span>polling every {tracker.interval >= 60 ? `${Math.round(tracker.interval / 60)} min` : `${tracker.interval} s`}{open ? "" : " until the open"}</span>
          <span className="faint">· last update {ago(tracker.last_poll)}{tracker.error ? "" : ""}</span>
        </span>}
        actions={<>
          <Popover className="menu" trigger={(o, toggle) => <button className={`btn sec ${o ? "on" : ""}`} onClick={toggle} title="Edit, focus, refresh and tracking"><Icon name="ellipsis" className="sm" />More</button>}>
            {(close) => (
              <>
                <button onClick={() => { close(); setEditing(!editing); }}><Icon name="edit" className="sm" />{editing ? "Close the editor" : "Edit name, notes and colour"}</button>
                <button onClick={() => { close(); scope.set(scope.id === list.id ? null : list.id); }}><Icon name="target" className="sm" />{scope.id === list.id ? "Stop focusing the app on this list" : "Focus the app on this list"}</button>
                <hr />
                <button onClick={() => { close(); m.poll.mutate(); }} disabled={tracker.paused || !items.length}><Icon name="refresh" className="sm" />Update prices now</button>
                <button onClick={() => { close(); m.tracker.mutate({ paused: !tracker.paused }); }}><Icon name={tracker.paused ? "debug-start" : "debug-pause"} className="sm" />{tracker.paused ? "Resume live tracking" : "Pause live tracking"}</button>
                <button onClick={() => { close(); setTracking(true); }}><Icon name="settings-gear" className="sm" />Tracking settings…</button>
              </>
            )}
          </Popover>
          {scope.id === list.id && <span className="tag info" title="The app shows only this list's companies">App focused here</span>}
          {items.length > 0 && <ResearchLauncher list={list} secondary />}
          <button className="btn" onClick={() => setAdding(true)} title={tracked >= max ? `The watchlists already track ${max} companies` : `Add companies to “${list.name}”`}><Icon name="add" className="sm" />Add companies</button>
        </>} />
      {adding && <AddCompanies list={list} items={items} room={max - tracked} onClose={() => setAdding(false)} />}
      {tracking && <TrackingDrawer tracker={tracker} onClose={() => setTracking(false)} />}
      {editing && <EditBar list={list} count={items.length} onClose={() => setEditing(false)} />}
      {tracker.error && <div className="note err"><Icon name="error" /><div>Last poll failed: {tracker.error}. The tracker keeps trying.</div></div>}
      {!items.length ? <EmptyWatch list={list} onAdd={() => setAdding(true)} /> : (
        <>
          <div className="band">{band.map((b) => <div key={b.k}><div className="k">{b.k}</div><div className="v">{b.v}</div><div className="s">{b.s}</div></div>)}</div>
          <div className={`split wl ${current ? "" : "closed"}`}>
            <section className="panel" style={{ minHeight: 0 }}>
              <div className="toolbar">
                <div className="seg"><button className={view === "tiles" ? "on" : ""} onClick={() => setView("tiles")}><Icon name="layout" className="xs" />Tiles</button><button className={view === "table" ? "on" : ""} onClick={() => setView("table")}><Icon name="list-flat" className="xs" />Table</button></div>
                <div className="search wl-find" title="Find a company on this list by name, symbol, sector or label">
                  <Icon name="search" /><input value={find} onChange={(e) => setFind(e.target.value)} placeholder={`Search ${items.length} companies`} aria-label="Search this watchlist"
                    onKeyDown={(e) => { if (e.key === "Escape") setFind(""); else if (e.key === "Enter" && sorted[0]) pick(sorted[0].ticker); }} />
                  {find && <button className="ibtn sm" onClick={() => setFind("")} title="Clear"><Icon name="close" className="xs" /></button>}
                </div>
                {find && <span className="xs faint">{shown.length} of {items.length}</span>}
                {view === "tiles" && <SortBar state={sortState} />}
                <span className="spacer" />
                {view === "tiles" && (
                  <label className="wl-pickall" title="Select every company">
                    <input type="checkbox" className="cb" checked={checked.size > 0 && checked.size === items.length}
                      ref={(el) => { if (el) el.indeterminate = checked.size > 0 && checked.size < items.length; }}
                      onChange={() => setChecked(checked.size === items.length ? new Set() : new Set(items.map((w) => w.ticker)))} />
                    <span className="xs">All</span>
                  </label>
                )}
                {!checked.size && !find && <span className="xs faint wl-hint">Click a company for its live view · <b>Full analysis</b> for everything</span>}
              </div>
              {checked.size > 0 && <BulkBar list={list} items={items} checked={checked} setChecked={setChecked} onClosed={(t) => { if (sel && t.includes(sel)) pick(null); }} />}
              {view === "tiles" ? (
                <div className="tiles">{sorted.map((w) => <Tile key={w.ticker} w={w} on={w.ticker === sel} picked={checked.has(w.ticker)} picking={checked.size > 0}
                  onPick={() => setChecked((c) => { const n = new Set(c); if (n.has(w.ticker)) n.delete(w.ticker); else n.add(w.ticker); return n; })}
                  onClick={() => pick(w.ticker === sel ? null : w.ticker)} onOpen={() => openFull(w.ticker)} />)}
                  {!sorted.length && <div className="xs faint" style={{ padding: 16 }}>No company on this list matches “{find}”.</div>}</div>
              ) : <WatchTable items={sorted} sel={sel} pick={pick} open={openFull} state={sortState} checked={checked} setChecked={setChecked} find={find} />}
            </section>
            {current && <Detail w={current} v={rows.find((r) => r.ticker === current.ticker)?.v ?? null} list={list} onClose={() => pick(null)} onOpen={() => openFull(current.ticker)} />}
          </div>
          <AlertsPanel />
        </>
      )}
    </>
  );
}

function Tile({ w, on, picked, picking, onPick, onClick, onOpen }: { w: WatchRow; on: boolean; picked: boolean; picking: boolean; onPick: () => void; onClick: () => void; onOpen: () => void }) {
  const q = w.quote;
  const up = (q?.chg_pct ?? 0) >= 0;
  const hm = q?.hm;
  const below = hm?.buy_below && isNum(q?.last) && q!.last! <= hm.buy_below;
  return (
    <div className={`tile ${on ? "on" : ""} ${below ? "value" : ""} ${picked ? "picked" : ""} ${picking ? "picking" : ""}`} role="button" tabIndex={0}
      onClick={(e) => (e.ctrlKey || e.metaKey || picking ? onPick() : onClick())} onDoubleClick={onOpen} title="Click for the live view · double-click for the full analysis"
      onKeyDown={(e) => { if (e.key === "Enter") (e.shiftKey ? onOpen() : onClick()); else if (e.key === " ") { e.preventDefault(); onPick(); } }}>
      <div className="tile-h">
        <input type="checkbox" className="cb tile-cb" checked={picked} onClick={(e) => e.stopPropagation()} onChange={onPick} aria-label={`Select ${w.name}`} title="Select" />
        <b className="ellipsis">{shortName(w.name)}</b>
        <span className="mono faint xs">{w.ticker.replace(/\.NS$/, "")}</span>
        {(w.alert_below || w.alert_above) && <Icon name="bell" className="xs" style={{ color: "var(--c-yellow)" }} />}
        {q?.stale && <Icon name="clock" className="xs warn" title={q.source?.startsWith("stored") ? "No data provider answered: showing the last stored price" : "No new price for 20 minutes (exchange holiday?)"} />}
        {(w.v?.red_flags?.length ?? 0) > 0 && <span className="tag down xs" title={w.v!.red_flags.join("\n")}>{w.v!.red_flags.length} flag{w.v!.red_flags.length > 1 ? "s" : ""}</span>}
        <button className="ibtn sm tile-open" onClick={(e) => { e.stopPropagation(); onOpen(); }} title="Full analysis"><Icon name="go-to-file" className="xs" /></button>
      </div>
      {q?.error ? <div className="xs down" style={{ padding: "12px 0" }}>{q.error}</div> : !q ? <div className="xs faint" style={{ padding: "12px 0" }}>waiting for the first poll…</div> : (
        <>
          <div className="tile-px">
            <span className="v">{num(q.last)}</span>
            <span className={`d ${up ? "up" : "down"}`}>{up ? "▲" : "▼"} {pct(Math.abs(q.chg_pct ?? 0), 2)}</span>
          </div>
          <Spark values={(q.spark?.length ?? 0) > 1 ? q.spark! : q.month ?? []} base={(q.spark?.length ?? 0) > 1 ? q.prev_close : undefined} width={220} height={42} />
          <div className="tile-r">
            <span className="xs faint">Day</span><Position lo={q.low} hi={q.high} value={q.last} width={150} />
          </div>
          <div className="tile-f">
            {hm ? <>
              <span className="xs" style={{ color: HM_COLOR }}>{money(hm.value, 0)}</span>
              <span className={`xs mono ${(hm.upside ?? 0) >= 0 ? "up" : "down"}`}>{pct(hm.upside, 0, true)}</span>
              <LabelBadge label={hm.label} />
            </> : <span className="xs faint">not valued — tracking price only</span>}
            <span className="spacer" />
            {isNum(w.since_added) && <span className={`xs mono ${w.since_added >= 0 ? "up" : "down"}`} title={`since you added it at ${num(w.added_price)}`}>{pct(w.since_added, 1, true)} since added</span>}
          </div>
        </>
      )}
    </div>
  );
}

const LABEL_RANK = (l: string | undefined) => (l ? LABELS.length - Math.max(0, LABELS.indexOf(l as (typeof LABELS)[number])) : null);
/** where the last price sits in the day's range, 0 (low) to 1 (high) */
const inRange = (w: WatchItem) => { const last = w.quote?.last, lo = w.quote?.low, hi = w.quote?.high; return isNum(last) && isNum(lo) && isNum(hi) && hi > lo ? (last - lo) / (hi - lo) : null; };
/** the move across today's sparkline */
const intraday = (w: WatchItem) => { const s = w.quote?.spark ?? [], a = s[0], b = s[s.length - 1]; return s.length > 1 && isNum(a) && isNum(b) && a ? b / a - 1 : null; };

// every column sorts: click a header (or, in tiles view, a column name above the tiles)
type WatchRow = WatchItem & { v?: Verdict | null };
const WATCH_COLUMNS: Column<WatchRow>[] = [
  { key: "company", header: "Company", sticky: true, fixed: true, sort: (w) => w.name, render: (w) => <div className="co"><b>{shortName(w.name)}</b><small>{w.ticker}</small></div> },
  { key: "spark", header: "Today", sort: intraday, exportValue: (w) => pct(intraday(w), 2, true), render: (w) => <Spark values={w.quote?.spark ?? []} base={w.quote?.prev_close} width={90} height={24} /> },
  { key: "last", header: "Last", align: "r", sort: (w) => w.quote?.last, render: (w) => <span className="mono">{num(w.quote?.last)}</span> },
  { key: "chg", header: "Change", align: "r", sort: (w) => w.quote?.chg_pct, exportValue: (w) => pct(w.quote?.chg_pct, 2, true), render: (w) => <span className={`mono ${(w.quote?.chg_pct ?? 0) >= 0 ? "up" : "down"}`}>{pct(w.quote?.chg_pct, 2, true)}</span> },
  { key: "day", header: "Day range", sort: inRange, exportValue: (w) => pct(inRange(w), 0), render: (w) => <Position lo={w.quote?.low} hi={w.quote?.high} value={w.quote?.last} width={80} /> },
  { key: "volume", header: "Volume", align: "r", sort: (w) => w.quote?.volume, render: (w) => <span className="mono muted">{w.quote?.volume?.toLocaleString("en-IN") ?? "—"}</span> },
  { key: "hm", header: "HYBRID MODEL", align: "r", sort: (w) => w.quote?.hm?.value, render: (w) => <span className="mono" style={{ color: HM_COLOR }}>{money(w.quote?.hm?.value, 0)}</span> },
  { key: "upside", header: "Live upside", align: "r", sort: (w) => w.quote?.hm?.upside, exportValue: (w) => pct(w.quote?.hm?.upside, 1, true), render: (w) => <span className={`mono ${(w.quote?.hm?.upside ?? 0) >= 0 ? "up" : "down"}`}>{pct(w.quote?.hm?.upside, 1, true)}</span> },
  { key: "label", header: "Label", sort: (w) => LABEL_RANK(w.quote?.hm?.label), exportValue: (w) => w.quote?.hm?.label ?? "", render: (w) => w.quote?.hm ? <LabelBadge label={w.quote.hm.label} /> : <span className="faint">—</span> },
  { key: "since", header: "Since added", align: "r", sort: (w) => w.since_added, exportValue: (w) => pct(w.since_added, 1, true), render: (w) => <span className={`mono ${(w.since_added ?? 0) >= 0 ? "up" : "down"}`}>{pct(w.since_added, 1, true)}</span> },
  { key: "alerts", header: "Alerts", sort: (w) => (w.alert_below ? 1 : 0) + (w.alert_above ? 1 : 0) || null,
    exportValue: (w) => `${w.alert_below ? `below ${num(w.alert_below, 0)}` : ""} ${w.alert_above ? `above ${num(w.alert_above, 0)}` : ""}`.trim(),
    render: (w) => <span className="mono xs muted">{w.alert_below ? `↓${num(w.alert_below, 0)}` : ""} {w.alert_above ? `↑${num(w.alert_above, 0)}` : ""}</span> },
  { key: "conf", header: "Confidence", sort: (w) => w.quote?.hm?.confidence ?? w.v?.confidence, exportValue: (w) => num(w.quote?.hm?.confidence ?? w.v?.confidence, 0),
    render: (w) => { const c = w.quote?.hm?.confidence ?? w.v?.confidence; return isNum(c) ? <div className="row"><Meter value={c} width={44} /><span className="mono muted xs">{c.toFixed(0)}</span></div> : <span className="faint">—</span>; } },
  { key: "research", header: "Research", sort: (w) => w.v?.research_score, exportValue: (w) => signed(w.v?.research_score),
    render: (w) => w.v ? <div className="row"><Diverge value={w.v.research_score} width={50} /><span className="mono muted xs">{signed(w.v.research_score)}</span></div> : <span className="faint xs">not researched</span> },
  { key: "flags", header: "Flags", align: "r", sort: (w) => w.v?.red_flags?.length ?? null, exportValue: (w) => (w.v?.red_flags ?? []).join(" | "),
    render: (w) => <span className={`mono ${(w.v?.red_flags?.length ?? 0) ? "down" : "faint"}`} title={(w.v?.red_flags ?? []).join("\n")}>{w.v ? w.v.red_flags?.length ?? 0 : "—"}</span> },
  { key: "buy", header: "Buy-below", align: "r", visible: false, sort: (w) => w.quote?.hm?.buy_below ?? w.v?.buy_below, render: (w) => <span className="mono muted">{money(w.quote?.hm?.buy_below ?? w.v?.buy_below, 0)}</span> },
  { key: "sector", header: "Sector", visible: false, sort: (w) => w.sector, render: (w) => <span className="muted">{w.sector}</span> },
];
type SortState = ReturnType<typeof useGridState<WatchRow>>;
/** the same rule as a header click: a new column starts high-to-low (names A-Z), a second click flips it */
const clickSort = (state: SortState, key: string) =>
  state.setSort({ key, asc: state.sort?.key === key ? !state.sort.asc : key === "company" || key === "sector" });

/** Tiles have no headers: the column names, as buttons, sort them. */
function SortBar({ state }: { state: SortState }) {
  return (
    <div className="wl-sortbar" role="group" aria-label="Sort by">
      <span className="xs faint">Sort</span>
      {WATCH_COLUMNS.filter((c) => c.sort && !["sector", "alerts", "research", "flags", "buy", "conf"].includes(c.key)).map((c) => {
        const on = state.sort?.key === c.key;
        return (
          <button key={c.key} className={on ? "on" : ""} onClick={() => clickSort(state, c.key)} title={`Sort by ${c.header.toLowerCase()}`}>
            {c.header}{on && <Icon name={state.sort!.asc ? "arrow-small-up" : "arrow-small-down"} className="xs" />}
          </button>
        );
      })}
    </div>
  );
}

function WatchTable({ items, sel, pick, open, state, checked, setChecked, find }: { items: WatchRow[]; sel: string | null; pick: (t: string | null) => void; open: (t: string) => void; state: SortState; checked: Set<string>; setChecked: (s: Set<string>) => void; find: string }) {
  return (
    <>
      <div className="toolbar wl-tabletools"><span className="xs faint">Enter or double-click opens the full analysis</span><span className="spacer" /><GridTools columns={WATCH_COLUMNS} state={state} exportRows={items} exportTitle="Watchlist" /></div>
      <DataGrid rows={items} columns={WATCH_COLUMNS} rowKey={(w) => w.ticker} state={state} selected={sel} onSelect={pick} onOpen={open} checked={checked} onCheck={setChecked}
        empty={find ? `No company on this list matches “${find}”.` : "No companies."} />
    </>
  );
}

/** What to do with the ticked companies: take them off, or move or copy them to another list. */
function BulkBar({ list, items, checked, setChecked, onClosed }: { list: WatchList; items: WatchItem[]; checked: Set<string>; setChecked: (s: Set<string>) => void; onClosed: (tickers: string[]) => void }) {
  const lib = useWatchlists();
  const lm = useWatchlistMutations();
  const app = useApp();
  const [busy, setBusy] = useState(false);
  const picked = items.filter((w) => checked.has(w.ticker));
  const others = (lib.data?.lists ?? []).filter((l) => l.id !== list.id);
  const say = (e: unknown) => app.toast(e instanceof Error ? e.message : String(e), "error");
  const payload = picked.map((w) => ({ ticker: w.ticker, name: w.name, sector: w.sector }));
  const takeOff = async (tickers: string[]) => { for (const t of tickers) await lm.removeOne(list.id, t); onClosed(tickers); };
  const remove = async () => {
    if (!confirm(`Take ${picked.length} compan${picked.length === 1 ? "y" : "ies"} off “${list.name}”? Companies on other lists stay tracked.`)) return;
    setBusy(true);
    try { await takeOff(picked.map((w) => w.ticker)); setChecked(new Set()); app.toast(`${picked.length} taken off “${list.name}”`, "ok"); } catch (e) { say(e); } finally { setBusy(false); }
  };
  const copyTo = async (id: string, move: boolean) => {
    const to = others.find((l) => l.id === id);
    if (!to) return;
    setBusy(true);
    try {
      const r = await lm.addMany.mutateAsync({ id, tickers: payload });
      if (move) await takeOff(picked.map((w) => w.ticker));
      setChecked(new Set());
      app.toast(`${move ? "Moved" : "Copied"} ${picked.length} to “${to.name}”${r.added < picked.length ? ` (${picked.length - r.added} were already there)` : ""}`, "ok");
    } catch (e) { say(e); } finally { setBusy(false); }
  };
  return (
    <div className="toolbar wl-bulk">
      <span className="tag info">{checked.size} selected</span>
      <button className="btn sm ghost" onClick={() => setChecked(new Set(items.map((w) => w.ticker)))} disabled={checked.size === items.length}>Select all {items.length}</button>
      {others.length > 0 && (
        <>
          <ActionMenu small label="Copy to" icon="copy" disabled={busy} title="Add them to another list as well" items={others.map((l) => ({ label: l.name, onClick: () => copyTo(l.id, false) }))} />
          <ActionMenu small label="Move to" icon="arrow-right" disabled={busy} title="Move them to another list" items={others.map((l) => ({ label: l.name, onClick: () => copyTo(l.id, true) }))} />
        </>
      )}
      <button className="btn danger sm" onClick={remove} disabled={busy}><Icon name={busy ? "loading" : "trash"} className={`sm ${busy ? "spin" : ""}`} />Remove from list</button>
      <span className="spacer" />
      <button className="btn sm ghost" onClick={() => setChecked(new Set())} title="Clear the selection"><Icon name="close" className="xs" />Clear</button>
    </div>
  );
}

/** The list's name, notes and colour, edited in place under the header. */
function EditBar({ list, count, onClose }: { list: WatchList; count: number; onClose: () => void }) {
  const lib = useWatchlists();
  const lm = useWatchlistMutations();
  const app = useApp();
  const nav = useNavigate();
  const [name, setName] = useState(list.name);
  const [desc, setDesc] = useState(list.description ?? "");
  const [color, setColor] = useState(list.color);
  const dirty = name.trim() !== list.name || desc.trim() !== (list.description ?? "") || color !== list.color;
  const save = () => lm.edit.mutate({ id: list.id, name: name.trim(), description: desc.trim(), color }, {
    onSuccess: () => { app.toast(`“${name.trim()}” saved`, "ok"); onClose(); },
    onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
  });
  const del = () => {
    if (!confirm(`Delete “${list.name}”? Companies on other lists stay tracked.`)) return;
    lm.remove.mutate(list.id, { onSuccess: () => { app.toast(`“${list.name}” deleted`, "ok"); nav("/watchlist"); }, onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error") });
  };
  return (
    <section className="panel wl-editbar" onKeyDown={(e) => { if (e.key === "Escape") onClose(); else if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && dirty && name.trim()) save(); }}>
      <div className="wl-editbar-f">
        <label className="fld"><span>Name</span><input className="inp" autoFocus maxLength={60} value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="fld grow"><span>Description</span><input className="inp" maxLength={400} value={desc} placeholder="What this list is for" onChange={(e) => setDesc(e.target.value)} /></label>
        <div className="fld"><span>Colour</span>
          <div className="wl-colors">{(lib.data?.colors ?? [list.color]).map((c) => <button key={c} className={c === color ? "on" : ""} style={{ background: c }} onClick={() => setColor(c)} title={c} aria-label={`Colour ${c}`} />)}</div>
        </div>
      </div>
      <div className="wl-editbar-b">
        <Icon name="info" className="xs faint" />
        <span className="xs faint grow">{count ? <>Tick companies below to remove them, or move or copy them to another list. <b>Add company</b> brings in more.</> : <>Add companies with <b>Add company</b> above.</>}</span>
        <button className="btn sm ghost danger-text" onClick={del}><Icon name="trash" className="xs" />Delete list</button>
        <button className="btn sm sec" onClick={onClose}>Done</button>
        <button className="btn sm" disabled={!dirty || !name.trim() || lm.edit.isPending} onClick={save}><Icon name="check" className="sm" />Save</button>
      </div>
    </section>
  );
}

/** The side panel for one company: live chart, its research in brief, the next hours and days, alerts. */
function Detail({ w, v, list, onClose, onOpen }: { w: WatchItem; v: Verdict | null; list: WatchList; onClose: () => void; onOpen: () => void }) {
  const hm = w.quote?.hm;
  return (
    <aside className="insp wl-detail">
      <div className="insp-h">
        <div className="row">
          <div className="grow" style={{ minWidth: 0 }}><div className="strong ellipsis" style={{ fontSize: 14 }}>{shortName(w.name)}</div><div className="faint xs mono">{w.ticker} · {w.sector}</div></div>
          <button className="ibtn" onClick={onClose} title="Close"><Icon name="close" /></button>
        </div>
        <button className="btn wl-full" onClick={onOpen}><Icon name="go-to-file" className="sm" />Full analysis<span className="xs faint">research, valuation, forecasts</span></button>
      </div>
      <div className="insp-b" style={{ gap: 12 }}>
        <ChartPanel ticker={w.ticker} watch={w} height={190} compactHead simple />
        {v ? (
          <div className="wl-brief">
            <div className="row" style={{ gap: 6 }}><span className="label">Research</span><LabelBadge label={hm?.label ?? v.label} /><span className="spacer" />{(v.red_flags?.length ?? 0) > 0 && <span className="tag down">{v.red_flags.length} red flag{v.red_flags.length > 1 ? "s" : ""}</span>}</div>
            {v.summary?.headline && <p className="small" style={{ lineHeight: 1.55, margin: 0 }}>{v.summary.headline}</p>}
            <div className="row xs muted" style={{ gap: 12, flexWrap: "wrap" }}>
              <span>Confidence <b className="mono">{isNum(hm?.confidence ?? v.confidence) ? (hm?.confidence ?? v.confidence)!.toFixed(0) : "—"}</b></span>
              <span>Research score <b className="mono">{signed(v.research_score)}</b></span>
              <span>Range <b className="mono">{money(v.low, 0)}–{money(v.high, 0)}</b></span>
            </div>
          </div>
        ) : <div className="xs faint">Not researched yet — <button className="linkish" onClick={onOpen}>open the full analysis</button> to start research on it.</div>}
        <LiveForecast ticker={w.ticker} compact />
        <WatchControls w={w} list={list} onRemoved={onClose} />
      </div>
    </aside>
  );
}

/** Add companies to this list: search, whole sectors, a spreadsheet or another list. */
function AddCompanies({ list, items, room, onClose }: { list: WatchList; items: WatchItem[]; room: number; onClose: () => void }) {
  const lm = useWatchlistMutations();
  const app = useApp();
  const [picks, setPicks] = useState<Entry[]>([]);
  const taken = useMemo(() => new Set(items.map((w) => w.ticker)), [items]);
  const save = () => lm.addMany.mutate({ id: list.id, tickers: picks }, {
    onSuccess: (r) => { app.toast(`${r.added} compan${r.added === 1 ? "y" : "ies"} added to “${list.name}”${r.failed.length ? ` · ${r.failed.length} not added (${r.failed[0]})` : ""}`, r.failed.length ? "info" : "ok"); onClose(); },
    onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
  });
  return (
    <Drawer title={`Add companies to “${list.name}”`} icon="add" wide onClose={onClose}
      footer={<><span className="xs faint">Every company added also joins the learning data for the AI/ML models.</span><span className="spacer" /><button className="btn sec" onClick={onClose}>Cancel</button>
        <button className="btn" disabled={!picks.length || lm.addMany.isPending} onClick={save}><Icon name={lm.addMany.isPending ? "loading" : "add"} className={`sm ${lm.addMany.isPending ? "spin" : ""}`} />Add {picks.length || ""}</button></>}>
      <CompanyImporter picks={picks} setPicks={setPicks} taken={taken} room={room} exceptList={list.id} />
    </Drawer>
  );
}

function TrackingDrawer({ tracker, onClose }: { tracker: TrackerState; onClose: () => void }) {
  const s = tracker.settings;
  const m = useWatchMutations();
  const app = useApp();
  const set = (patch: Record<string, unknown>) => m.tracker.mutate(patch, { onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error") });
  return (
    <Drawer title="Live tracking" icon="settings-gear" onClose={onClose} footer={<><span className="spacer" /><button className="btn" onClick={onClose}>Done</button></>}>
      <div className="col" style={{ gap: 12 }}>
        <Toggle checked={!s.paused} onChange={(v) => set({ paused: !v })} label="Track every watchlist's prices live" />
        <label className="fld"><span>Check prices every (seconds) while the market is open</span><input className="inp sm num" type="number" min={15} max={600} defaultValue={s.poll_open} onBlur={(e) => set({ poll_open: Number(e.target.value) })} /></label>
        <label className="fld"><span>Check prices every (seconds) while it is closed</span><input className="inp sm num" type="number" min={60} max={7200} defaultValue={s.poll_closed} onBlur={(e) => set({ poll_closed: Number(e.target.value) })} /></label>
        <label className="fld"><span>Alert on a daily move of at least (%)</span><input className="inp sm num" type="number" min={0} max={50} step={0.5} defaultValue={(s.move_alert * 100).toFixed(1)} onBlur={(e) => set({ move_alert: Number(e.target.value) / 100 })} /></label>
        <label className="fld"><span>Keep minute-by-minute prices for (days)</span><input className="inp sm num" type="number" min={7} max={3650} defaultValue={s.retention_days} onBlur={(e) => set({ retention_days: Number(e.target.value) })} /></label>
        <span className="xs faint">Yahoo keeps only 7 days of minute prices; the tracker stores its own copy for as long as you set here. When Yahoo has no price for a company, the NSE and BSE websites are asked instead.</span>
      </div>
    </Drawer>
  );
}

function EmptyWatch({ list, onAdd }: { list: WatchList; onAdd: () => void }) {
  return (
    <Panel>
      <Empty icon="eye" title={`“${list.name}” is empty`} action={<div className="row"><button className="btn" onClick={onAdd}><Icon name="add" className="sm" />Add companies</button><Link className="btn sec" to="/markets">Browse Markets</Link></div>}>
        Search for companies, take whole sectors, or import a spreadsheet. While the market is open the tracker checks prices every 30 seconds, re-values covered companies at the live price, and alerts you on the levels you set.
      </Empty>
    </Panel>
  );
}

function AlertsPanel() {
  const q = useLiveAlerts();
  const qc = useQueryClient();
  const unseen = (q.data ?? []).filter((a) => !a.seen).length;
  const ICON: Record<string, string> = { below: "arrow-down", above: "arrow-up", buy_below: "tag", move: "pulse" };
  const refresh = () => qc.invalidateQueries({ queryKey: ["live-alerts"] });
  const del = (id: number) => { chime("ui"); api.del(`/api/live/alerts/${id}`).then(refresh).catch(refresh); };
  const clear = () => { if (confirm(`Delete all ${q.data?.length ?? 0} alerts?`)) { chime("ui"); api.del("/api/live/alerts").then(refresh).catch(refresh); } };
  return (
    <Panel title="Live alerts" meta={unseen ? `${unseen} new` : "price levels, buy-below crossings and big daily moves"}
      tools={<>
        {unseen > 0 && <button className="btn xs ghost" onClick={() => api.post("/api/live/alerts/seen").then(refresh)}>Mark all read</button>}
        {(q.data?.length ?? 0) > 0 && <button className="btn xs ghost" onClick={clear}><Icon name="clear-all" className="xs" />Clear all</button>}
      </>} flush>
      {q.isError ? <div style={{ padding: 12 }}><ErrorNote error={q.error} /></div> : !(q.data ?? []).length ? (
        <div className="empty" style={{ padding: 24 }}><Icon name="bell" /><span className="small">No alerts yet.</span></div>
      ) : (
        <div className="feed" style={{ maxHeight: 260 }}>
          {q.data!.slice(0, 50).map((a) => (
            <div key={a.id} className={`ev ev-x ${a.seen ? "" : "new"}`}>
              <span className="ic"><Icon name={ICON[a.kind] ?? "bell"} className={`sm ${a.kind === "below" || a.kind === "buy_below" ? "up" : a.kind === "above" ? "warn" : "info"}`} /></span>
              <div className="grow"><div className="t">{a.message}</div><div className="d">{when(a.t)} · session {a.session}</div></div>
              <button className="ibtn sm" title="Delete this alert" onClick={() => del(a.id)}><Icon name="close" className="xs" /></button>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
