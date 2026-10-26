import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useCompanies, useStartJob, useStatus } from "../lib/hooks";
import { isOpen, TrackerState, useLiveAlerts, useLiveSearch, useSectors, useWatchlist, useWatchlistMutations, useWatchlists, useWatchMutations, WatchItem, WatchList } from "../lib/live";
import { useScope } from "../lib/scope";
import { ResearchList } from "./WatchlistLibrary";
import { ago, isNum, money, num, pct, shortName, when } from "../lib/format";
import { HM_COLOR, LABELS } from "../lib/labels";
import { Empty, ErrorNote, Icon, LabelBadge, PageHeader, Panel, Popover, QueryView, Toggle } from "../components/ui";
import { Column, DataGrid, GridTools, sortRows, useGridState } from "../components/DataGrid";
import { ChartPanel } from "../components/ChartPanel";
import { Position, Spark } from "../components/Spark";
import { useApp } from "../components/workbenchContext";
import { chime } from "../lib/notify";


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
  const sortState = useGridState<WatchItem>("watch", WATCH_COLUMNS, { key: "chg", asc: false });
  useEffect(() => { try { localStorage.setItem("wl.view", view); } catch { /* ignore */ } }, [view]);
  const m = useWatchMutations();
  const alerts = useLiveAlerts();
  const open = isOpen(tracker.market);
  const current = items.find((w) => w.ticker === sel) ?? null;

  const sorted = useMemo(() => sortRows(items, WATCH_COLUMNS, sortState.sort), [items, sortState.sort]);

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
          <TrackerSettings tracker={tracker} />
          <button className="btn sec" onClick={() => m.tracker.mutate({ paused: !tracker.paused })}><Icon name={tracker.paused ? "debug-start" : "debug-pause"} className="sm" />{tracker.paused ? "Resume" : "Pause"}</button>
          <button className="btn sec" onClick={() => m.poll.mutate()} disabled={tracker.paused || !items.length}><Icon name={m.poll.isPending ? "loading" : "refresh"} className={`sm ${m.poll.isPending ? "spin" : ""}`} />Update now</button>
          <button className={`btn sec ${scope.id === list.id ? "on" : ""}`} onClick={() => scope.set(scope.id === list.id ? null : list.id)} title="Show only this list's companies across the app">
            <Icon name="target" className="sm" />{scope.id === list.id ? "App focused here" : "Focus the app"}</button>
          <ResearchList list={list} />
          <button className={`btn sec ${editing ? "on" : ""}`} onClick={() => setEditing(!editing)}><Icon name="edit" className="sm" />{editing ? "Editing" : "Edit list"}</button>
          <AddCompany count={tracked} max={max} listId={list.id} listName={list.name} />
        </>} />
      {editing && <EditBar list={list} count={items.length} onClose={() => setEditing(false)} />}
      {tracker.error && <div className="note err"><Icon name="error" /><div>Last poll failed: {tracker.error}. The tracker keeps trying.</div></div>}
      {!items.length ? <EmptyWatch list={list} /> : (
        <>
          <div className="band">{band.map((b) => <div key={b.k}><div className="k">{b.k}</div><div className="v">{b.v}</div><div className="s">{b.s}</div></div>)}</div>
          <div className={`split wl ${current ? "" : "closed"}`}>
            <section className="panel" style={{ minHeight: 0 }}>
              <div className="toolbar">
                <div className="seg"><button className={view === "tiles" ? "on" : ""} onClick={() => setView("tiles")}><Icon name="layout" className="xs" />Tiles</button><button className={view === "table" ? "on" : ""} onClick={() => setView("table")}><Icon name="list-flat" className="xs" />Table</button></div>
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
                {!checked.size && <span className="xs faint">Tick companies to remove, move or copy several · click one for its chart</span>}
              </div>
              {checked.size > 0 && <BulkBar list={list} items={items} checked={checked} setChecked={setChecked} onClosed={(t) => { if (sel && t.includes(sel)) pick(null); }} />}
              {view === "tiles" ? (
                <div className="tiles">{sorted.map((w) => <Tile key={w.ticker} w={w} on={w.ticker === sel} picked={checked.has(w.ticker)} picking={checked.size > 0}
                  onPick={() => setChecked((c) => { const n = new Set(c); if (n.has(w.ticker)) n.delete(w.ticker); else n.add(w.ticker); return n; })}
                  onClick={() => pick(w.ticker === sel ? null : w.ticker)} />)}</div>
              ) : <WatchTable items={items} sel={sel} pick={pick} state={sortState} checked={checked} setChecked={setChecked} />}
            </section>
            {current && <Detail w={current} list={list} onClose={() => pick(null)} />}
          </div>
          <AlertsPanel />
        </>
      )}
    </>
  );
}

function Tile({ w, on, picked, picking, onPick, onClick }: { w: WatchItem; on: boolean; picked: boolean; picking: boolean; onPick: () => void; onClick: () => void }) {
  const q = w.quote;
  const up = (q?.chg_pct ?? 0) >= 0;
  const hm = q?.hm;
  const below = hm?.buy_below && isNum(q?.last) && q!.last! <= hm.buy_below;
  return (
    <div className={`tile ${on ? "on" : ""} ${below ? "value" : ""} ${picked ? "picked" : ""} ${picking ? "picking" : ""}`} role="button" tabIndex={0}
      onClick={(e) => (e.ctrlKey || e.metaKey || picking ? onPick() : onClick())} onKeyDown={(e) => { if (e.key === "Enter") onClick(); else if (e.key === " ") { e.preventDefault(); onPick(); } }}>
      <div className="tile-h">
        <input type="checkbox" className="cb tile-cb" checked={picked} onClick={(e) => e.stopPropagation()} onChange={onPick} aria-label={`Select ${w.name}`} title="Select" />
        <b className="ellipsis">{shortName(w.name)}</b>
        <span className="mono faint xs">{w.ticker.replace(/\.NS$/, "")}</span>
        {(w.alert_below || w.alert_above) && <Icon name="bell" className="xs" style={{ color: "var(--c-yellow)" }} />}
        {q?.stale && <Icon name="clock" className="xs warn" title="No new price for 20 minutes (exchange holiday?)" />}
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
const WATCH_COLUMNS: Column<WatchItem>[] = [
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
  { key: "sector", header: "Sector", visible: false, sort: (w) => w.sector, render: (w) => <span className="muted">{w.sector}</span> },
];
type SortState = ReturnType<typeof useGridState<WatchItem>>;
/** the same rule as a header click: a new column starts high-to-low (names A-Z), a second click flips it */
const clickSort = (state: SortState, key: string) =>
  state.setSort({ key, asc: state.sort?.key === key ? !state.sort.asc : key === "company" || key === "sector" });

/** Tiles have no headers: the column names, as buttons, sort them. */
function SortBar({ state }: { state: SortState }) {
  return (
    <div className="wl-sortbar" role="group" aria-label="Sort by">
      <span className="xs faint">Sort</span>
      {WATCH_COLUMNS.filter((c) => c.sort && c.key !== "sector" && c.key !== "alerts").map((c) => {
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

function WatchTable({ items, sel, pick, state, checked, setChecked }: { items: WatchItem[]; sel: string | null; pick: (t: string | null) => void; state: SortState; checked: Set<string>; setChecked: (s: Set<string>) => void }) {
  return (
    <>
      <div className="toolbar" style={{ borderTop: 0, paddingTop: 0 }}><span className="spacer" /><GridTools columns={WATCH_COLUMNS} state={state} exportRows={items} exportTitle="Watchlist" /></div>
      <DataGrid rows={items} columns={WATCH_COLUMNS} rowKey={(w) => w.ticker} state={state} selected={sel} onSelect={pick} onOpen={pick} checked={checked} onCheck={setChecked} />
    </>
  );
}

/** What to do with the ticked companies: take them off, move or copy them to another list, research them. */
function BulkBar({ list, items, checked, setChecked, onClosed }: { list: WatchList; items: WatchItem[]; checked: Set<string>; setChecked: (s: Set<string>) => void; onClosed: (tickers: string[]) => void }) {
  const lib = useWatchlists();
  const lm = useWatchlistMutations();
  const companies = useCompanies();
  const start = useStartJob();
  const status = useStatus();
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
  const covered = new Set((companies.data ?? []).map((c) => (c.ticker || "").toUpperCase().split(".")[0]));
  const researchable = picked.map((w) => w.ticker.toUpperCase().split(".")[0]).filter((t) => covered.has(t));
  const research = (quick: boolean) => start.mutate({ kind: "agents", options: { quick, tickers: researchable.join(",") } }, {
    onSuccess: (j) => { app.toast(`Researching ${researchable.length} compan${researchable.length === 1 ? "y" : "ies"}`, "ok"); app.showJob(j.id); }, onError: say,
  });
  return (
    <div className="toolbar wl-bulk">
      <span className="tag info">{checked.size} selected</span>
      <button className="btn sm ghost" onClick={() => setChecked(new Set(items.map((w) => w.ticker)))} disabled={checked.size === items.length}>Select all {items.length}</button>
      {others.length > 0 && (
        <>
          <select className="sel sm" value="" disabled={busy} onChange={(e) => copyTo(e.target.value, false)} title="Add them to another list as well">
            <option value="">Copy to…</option>{others.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
          <select className="sel sm" value="" disabled={busy} onChange={(e) => copyTo(e.target.value, true)} title="Move them to another list">
            <option value="">Move to…</option>{others.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </>
      )}
      <select className="sel sm" value="" disabled={busy || !researchable.length || !!status.data?.active_job || start.isPending}
        onChange={(e) => e.target.value && research(e.target.value === "quick")}
        title={!researchable.length ? "None of the selected companies is in Coverage yet" : status.data?.active_job ? "Another run is in progress" : `Research the ${researchable.length} covered companies`}>
        <option value="">Research…</option><option value="quick">Quick sweep ({researchable.length})</option><option value="full">Full research ({researchable.length})</option>
      </select>
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

function Detail({ w, list, onClose }: { w: WatchItem; list: WatchList; onClose: () => void }) {
  const m = useWatchMutations();
  const app = useApp();
  const [below, setBelow] = useState(w.alert_below?.toString() ?? "");
  const [above, setAbove] = useState(w.alert_above?.toString() ?? "");
  const [note, setNote] = useState(w.note ?? "");
  useEffect(() => { setBelow(w.alert_below?.toString() ?? ""); setAbove(w.alert_above?.toString() ?? ""); setNote(w.note ?? ""); }, [w.ticker, w.alert_below, w.alert_above, w.note]);
  const dirty = below !== (w.alert_below?.toString() ?? "") || above !== (w.alert_above?.toString() ?? "") || note !== (w.note ?? "");
  const save = () => m.update.mutate({ ticker: w.ticker, alert_below: below || null, alert_above: above || null, note }, {
    onSuccess: () => app.toast("Alerts saved", "ok"), onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
  });
  const last = w.quote?.last;
  return (
    <aside className="insp wl-detail">
      <div className="insp-h">
        <div className="row"><span className="grow strong">Live detail</span><button className="ibtn" onClick={onClose} title="Close"><Icon name="close" /></button></div>
      </div>
      <div className="insp-b" style={{ gap: 12 }}>
        <ChartPanel ticker={w.ticker} watch={w} height={190} compactHead simple />
        <div className="wl-form">
          <div className="label">Price alerts</div>
          <div className="row">
            <label className="fld grow"><span>Alert when at or below</span><input className="inp sm num" inputMode="decimal" value={below} placeholder={isNum(last) ? num(last * 0.95, 0) : "price"} onChange={(e) => setBelow(e.target.value.replace(/[^\d.]/g, ""))} /></label>
            <label className="fld grow"><span>Alert when at or above</span><input className="inp sm num" inputMode="decimal" value={above} placeholder={isNum(last) ? num(last * 1.05, 0) : "price"} onChange={(e) => setAbove(e.target.value.replace(/[^\d.]/g, ""))} /></label>
          </div>
          <span className="xs faint">Also alerted automatically when the price falls below the HYBRID MODEL buy-below, or moves more than the daily-move limit.</span>
          <label className="fld"><span>Note</span><textarea className="inp" rows={3} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="Why you are watching it" /></label>
          <div className="row">
            <button className="btn sm" disabled={!dirty || m.update.isPending} onClick={save}>Save</button>
            <span className="spacer" />
            <button className="btn sm ghost" onClick={() => { if (confirm(`Take ${w.name} off “${list.name}”?${(w.lists?.length ?? 1) > 1 ? " It stays on your other lists." : " Its stored minute bars are kept."}`)) m.remove.mutate({ ticker: w.ticker, list: list.id }, { onSuccess: onClose }); }}><Icon name="trash" className="xs" />Remove from list</button>
          </div>
          {(w.lists?.length ?? 0) > 1 && <WatchedOn ids={w.lists!} current={list.id} />}
          <div className="xs faint">Added {when(w.added)}{isNum(w.added_price) ? ` at ${num(w.added_price)}` : ""} · {w.sector} · <Link to={`/markets?t=${encodeURIComponent(w.ticker)}`}>Open in Markets</Link></div>
        </div>
      </div>
    </aside>
  );
}

function AddCompany({ count, max, listId, listName }: { count: number; max: number; listId: string; listName: string }) {
  const [text, setText] = useState("");
  const [sector, setSector] = useState("");
  const s = useLiveSearch(text);
  const sectors = useSectors();
  const m = useWatchMutations();
  const app = useApp();
  const add = (ticker: string, name?: string, sec?: string, cap?: string, close?: () => void) =>
    m.add.mutate({ ticker, name, sector: sec || sector || undefined, cap, list: listId }, {
      onSuccess: () => { app.toast(`${name ?? ticker} added to “${listName}”`, "ok"); setText(""); close?.(); },
      onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
    });
  return (
    <Popover className="pop" trigger={(open, toggle) => <button className={`btn ${open ? "on" : ""}`} onClick={toggle} title={count >= max ? `The watchlists already track ${max} companies` : `Add a company to “${listName}”`}><Icon name="add" className="sm" />Add company</button>}>
      {(close) => (
        <div style={{ width: 380 }}>
          <div className="search" style={{ margin: 10 }}><Icon name="search" /><input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="Company name or NSE symbol" /></div>
          <div className="feed" style={{ maxHeight: 300 }}>
            {(s.data ?? []).map((r) => (
              <div key={r.ticker} className="ev" onClick={() => add(r.ticker, r.lookup ? undefined : r.name, r.sector, r.cap, close)}>
                <span className="ic"><Icon name={r.lookup ? "globe" : "add"} className="sm" /></span>
                <div><div className="t">{r.lookup ? `Track ${r.ticker}` : shortName(r.name)}</div><div className="d mono">{r.lookup ? "not in your lists — choose its sector below" : `${r.ticker} · ${r.sector}`}</div></div>
              </div>
            ))}
          </div>
          {(s.data ?? []).some((r) => r.lookup) && (
            <div style={{ padding: 10, borderTop: "1px solid var(--line)" }}>
              <label className="fld"><span>Sector for a new symbol (used when it trains the models)</span>
                <select className="sel sm" value={sector} onChange={(e) => setSector(e.target.value)}><option value="">Unclassified</option>{(sectors.data ?? []).map((x) => <option key={x}>{x}</option>)}</select></label>
            </div>
          )}
          <div className="xs faint" style={{ padding: "8px 12px" }}>Every tracked company also joins the learning data for the AI/ML models.</div>
        </div>
      )}
    </Popover>
  );
}

function TrackerSettings({ tracker }: { tracker: TrackerState }) {
  const s = tracker.settings;
  const m = useWatchMutations();
  const app = useApp();
  const set = (patch: Record<string, unknown>) => m.tracker.mutate(patch, { onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error") });
  return (
    <Popover className="pop" trigger={(open, toggle) => <button className={`btn sec ${open ? "on" : ""}`} onClick={toggle}><Icon name="settings-gear" className="sm" />Tracking</button>}>
      {() => (
        <div className="col" style={{ width: 300, padding: 14, gap: 10 }}>
          <div className="label">Tracking</div>
          <Toggle checked={!s.paused} onChange={(v) => set({ paused: !v })} label="Track the watchlist" />
          <label className="fld"><span>Poll every (seconds) while the market is open</span><input className="inp sm num" type="number" min={15} max={600} defaultValue={s.poll_open} onBlur={(e) => set({ poll_open: Number(e.target.value) })} /></label>
          <label className="fld"><span>Poll every (seconds) while it is closed</span><input className="inp sm num" type="number" min={60} max={7200} defaultValue={s.poll_closed} onBlur={(e) => set({ poll_closed: Number(e.target.value) })} /></label>
          <label className="fld"><span>Alert on a daily move of at least (%)</span><input className="inp sm num" type="number" min={0} max={50} step={0.5} defaultValue={(s.move_alert * 100).toFixed(1)} onBlur={(e) => set({ move_alert: Number(e.target.value) / 100 })} /></label>
          <label className="fld"><span>Keep minute bars for (days)</span><input className="inp sm num" type="number" min={7} max={3650} defaultValue={s.retention_days} onBlur={(e) => set({ retention_days: Number(e.target.value) })} /></label>
          <span className="xs faint">Yahoo serves only 7 days of minute bars; the tracker keeps its own copy for as long as you set here.</span>
        </div>
      )}
    </Popover>
  );
}

function EmptyWatch({ list }: { list: WatchList }) {
  const companies = useCompanies();
  const lm = useWatchlistMutations();
  const app = useApp();
  const list_ = (companies.data ?? []).filter((c) => c.ticker);
  const addAll = () => lm.addMany.mutate({ id: list.id, tickers: list_.map((c) => ({ ticker: c.ticker, name: c.name, sector: c.sector, cap: c.cap })) }, {
    onSuccess: (r) => app.toast(`${r.added} companies added${r.failed.length ? ` · ${r.failed.length} not added (${r.failed[0]})` : ""}`, r.failed.length ? "info" : "ok"),
    onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
  });
  return (
    <Panel>
      <Empty icon="eye" title={`“${list.name}” is empty`} action={<div className="row">{list_.length > 0 && <button className="btn" onClick={addAll} disabled={lm.addMany.isPending}><Icon name={lm.addMany.isPending ? "loading" : "add"} className={`sm ${lm.addMany.isPending ? "spin" : ""}`} />Add my {list_.length} covered companies</button>}<Link className="btn sec" to="/markets">Find companies in Markets</Link></div>}>
        Add companies with <b>Add company</b> above. While the market is open the tracker polls every 30 seconds, stores every minute bar on this computer, re-values covered companies at the live price, and alerts you on the levels you set.
      </Empty>
    </Panel>
  );
}

/** The other lists a company is on, as chips that open them. */
function WatchedOn({ ids, current }: { ids: string[]; current: string }) {
  const lib = useWatchlists();
  const nav = useNavigate();
  const others = (lib.data?.lists ?? []).filter((l) => ids.includes(l.id) && l.id !== current);
  if (!others.length) return null;
  return (
    <div className="row xs" style={{ gap: 4, flexWrap: "wrap" }}>
      <span className="faint">Also on</span>
      {others.map((l) => <button key={l.id} className="wl-chip" style={{ ["--wc" as string]: l.color }} onClick={() => nav(`/watchlist/${encodeURIComponent(l.id)}`)}><i />{l.name}</button>)}
    </div>
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
