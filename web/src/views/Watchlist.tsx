import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useCompanies } from "../lib/hooks";
import { isOpen, TrackerState, useLiveAlerts, useLiveSearch, useSectors, useWatchlist, useWatchMutations, WatchItem } from "../lib/live";
import { ago, isNum, money, num, pct, shortName, when } from "../lib/format";
import { HM_COLOR } from "../lib/labels";
import { Empty, ErrorNote, Icon, LabelBadge, PageHeader, Panel, Popover, QueryView, Toggle } from "../components/ui";
import { Column, DataGrid, GridTools, useGridState } from "../components/DataGrid";
import { ChartPanel } from "../components/ChartPanel";
import { Position, Spark } from "../components/Spark";
import { useApp } from "../components/workbenchContext";

type Sort = "change" | "name" | "upside" | "since";

export function Watchlist() {
  const q = useWatchlist();
  const [params, setParams] = useSearchParams();
  const sel = params.get("t");
  const pick = (t: string | null) => { const p = new URLSearchParams(params); if (t) p.set("t", t); else p.delete("t"); setParams(p, { replace: true }); };
  return (
    <div className="page">
      <QueryView q={q} rows={10}>
        {(d) => <Board items={d.items} tracker={d.tracker} sel={sel} pick={pick} />}
      </QueryView>
    </div>
  );
}

function Board({ items, tracker, sel, pick }: { items: WatchItem[]; tracker: TrackerState; sel: string | null; pick: (t: string | null) => void }) {
  const [view, setView] = useState<"tiles" | "table">(() => { try { return (localStorage.getItem("wl.view") as "tiles" | "table") || "tiles"; } catch { return "tiles"; } });
  const [sort, setSort] = useState<Sort>("change");
  useEffect(() => { try { localStorage.setItem("wl.view", view); } catch { /* ignore */ } }, [view]);
  const m = useWatchMutations();
  const alerts = useLiveAlerts();
  const open = isOpen(tracker.market);
  const current = items.find((w) => w.ticker === sel) ?? null;

  const sorted = useMemo(() => {
    const key: Record<Sort, (w: WatchItem) => number | string> = {
      change: (w) => -(w.quote?.chg_pct ?? -9), name: (w) => w.name, upside: (w) => -(w.quote?.hm?.upside ?? -9), since: (w) => -(w.since_added ?? -9),
    };
    return [...items].sort((a, b) => (key[sort](a) < key[sort](b) ? -1 : key[sort](a) > key[sort](b) ? 1 : 0));
  }, [items, sort]);

  const q = items.map((w) => w.quote).filter((x) => x && isNum(x.chg_pct));
  const today = new Date().toISOString().slice(0, 10);
  const band = [
    { k: "Tracked", v: String(items.length), s: `of 60 · ${tracker.stored_bars?.toLocaleString("en-IN") ?? 0} minute bars stored` },
    { k: "Advancing / declining", v: `${q.filter((x) => x!.chg_pct! > 0).length} / ${q.filter((x) => x!.chg_pct! < 0).length}`, s: "last session" },
    { k: "Average change", v: q.length ? pct(q.reduce((a, x) => a + x!.chg_pct!, 0) / q.length, 2, true) : "—", s: "equal-weighted" },
    { k: "Below buy-below", v: String(items.filter((w) => w.quote?.hm?.buy_below && (w.quote.last ?? Infinity) <= w.quote.hm.buy_below).length), s: "HYBRID MODEL at the live price" },
    { k: "Alerts", v: String((alerts.data ?? []).filter((a) => new Date(a.t * 1000).toISOString().slice(0, 10) === today).length), s: "today" },
  ];

  return (
    <>
      <PageHeader crumbs={[{ label: "Analysis" }, { label: "Watchlist" }]} title="Watchlist"
        sub={<span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <span className={`live-dot ${open && !tracker.paused ? "on" : ""}`}>{tracker.paused ? "Tracking paused" : open ? "Tracking live" : "Market closed"}</span>
          <span>polling every {tracker.interval >= 60 ? `${Math.round(tracker.interval / 60)} min` : `${tracker.interval} s`}{open ? "" : " until the open"}</span>
          <span className="faint">· last update {ago(tracker.last_poll)}{tracker.error ? "" : ""}</span>
        </span>}
        actions={<>
          <TrackerSettings tracker={tracker} />
          <button className="btn sec" onClick={() => m.tracker.mutate({ paused: !tracker.paused })}><Icon name={tracker.paused ? "debug-start" : "debug-pause"} className="sm" />{tracker.paused ? "Resume" : "Pause"}</button>
          <button className="btn sec" onClick={() => m.poll.mutate()} disabled={tracker.paused || !items.length}><Icon name={m.poll.isPending ? "loading" : "refresh"} className={`sm ${m.poll.isPending ? "spin" : ""}`} />Update now</button>
          <AddCompany count={items.length} />
        </>} />
      {tracker.error && <div className="note err"><Icon name="error" /><div>Last poll failed: {tracker.error}. The tracker keeps trying.</div></div>}
      {!items.length ? <EmptyWatch /> : (
        <>
          <div className="band">{band.map((b) => <div key={b.k}><div className="k">{b.k}</div><div className="v">{b.v}</div><div className="s">{b.s}</div></div>)}</div>
          <div className={`split wl ${current ? "" : "closed"}`}>
            <section className="panel" style={{ minHeight: 0 }}>
              <div className="toolbar">
                <div className="seg"><button className={view === "tiles" ? "on" : ""} onClick={() => setView("tiles")}><Icon name="layout" className="xs" />Tiles</button><button className={view === "table" ? "on" : ""} onClick={() => setView("table")}><Icon name="list-flat" className="xs" />Table</button></div>
                {view === "tiles" && <select className="sel sm" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
                  <option value="change">Sort: today's change</option><option value="upside">Sort: live upside</option><option value="since">Sort: since added</option><option value="name">Sort: name</option>
                </select>}
                <span className="spacer" />
                <span className="xs faint">Click a company for its live chart, alerts and note</span>
              </div>
              {view === "tiles" ? (
                <div className="tiles">{sorted.map((w) => <Tile key={w.ticker} w={w} on={w.ticker === sel} onClick={() => pick(w.ticker === sel ? null : w.ticker)} />)}</div>
              ) : <WatchTable items={items} sel={sel} pick={pick} />}
            </section>
            {current && <Detail w={current} onClose={() => pick(null)} />}
          </div>
          <AlertsPanel />
        </>
      )}
    </>
  );
}

function Tile({ w, on, onClick }: { w: WatchItem; on: boolean; onClick: () => void }) {
  const q = w.quote;
  const up = (q?.chg_pct ?? 0) >= 0;
  const hm = q?.hm;
  const below = hm?.buy_below && isNum(q?.last) && q!.last! <= hm.buy_below;
  return (
    <button className={`tile ${on ? "on" : ""} ${below ? "value" : ""}`} onClick={onClick}>
      <div className="tile-h">
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
    </button>
  );
}

function WatchTable({ items, sel, pick }: { items: WatchItem[]; sel: string | null; pick: (t: string | null) => void }) {
  const columns: Column<WatchItem>[] = [
    { key: "company", header: "Company", sticky: true, fixed: true, sort: (w) => w.name, render: (w) => <div className="co"><b>{shortName(w.name)}</b><small>{w.ticker}</small></div> },
    { key: "spark", header: "Today", render: (w) => <Spark values={w.quote?.spark ?? []} base={w.quote?.prev_close} width={90} height={24} /> },
    { key: "last", header: "Last", align: "r", sort: (w) => w.quote?.last, render: (w) => <span className="mono">{num(w.quote?.last)}</span> },
    { key: "chg", header: "Change", align: "r", sort: (w) => w.quote?.chg_pct, render: (w) => <span className={`mono ${(w.quote?.chg_pct ?? 0) >= 0 ? "up" : "down"}`}>{pct(w.quote?.chg_pct, 2, true)}</span> },
    { key: "day", header: "Day range", render: (w) => <Position lo={w.quote?.low} hi={w.quote?.high} value={w.quote?.last} width={80} /> },
    { key: "volume", header: "Volume", align: "r", sort: (w) => w.quote?.volume, render: (w) => <span className="mono muted">{w.quote?.volume?.toLocaleString("en-IN") ?? "—"}</span> },
    { key: "hm", header: "HYBRID MODEL", align: "r", sort: (w) => w.quote?.hm?.value, render: (w) => <span className="mono" style={{ color: HM_COLOR }}>{money(w.quote?.hm?.value, 0)}</span> },
    { key: "upside", header: "Live upside", align: "r", sort: (w) => w.quote?.hm?.upside, render: (w) => <span className={`mono ${(w.quote?.hm?.upside ?? 0) >= 0 ? "up" : "down"}`}>{pct(w.quote?.hm?.upside, 1, true)}</span> },
    { key: "label", header: "Label", sort: (w) => w.quote?.hm?.label ?? "", render: (w) => w.quote?.hm ? <LabelBadge label={w.quote.hm.label} /> : <span className="faint">—</span> },
    { key: "since", header: "Since added", align: "r", sort: (w) => w.since_added, render: (w) => <span className={`mono ${(w.since_added ?? 0) >= 0 ? "up" : "down"}`}>{pct(w.since_added, 1, true)}</span> },
    { key: "alerts", header: "Alerts", render: (w) => <span className="mono xs muted">{w.alert_below ? `↓${num(w.alert_below, 0)}` : ""} {w.alert_above ? `↑${num(w.alert_above, 0)}` : ""}</span> },
    { key: "sector", header: "Sector", visible: false, sort: (w) => w.sector, render: (w) => <span className="muted">{w.sector}</span> },
  ];
  const state = useGridState<WatchItem>("watch", columns, { key: "chg", asc: false });
  return (
    <>
      <div className="toolbar" style={{ borderTop: 0, paddingTop: 0 }}><span className="spacer" /><GridTools columns={columns} state={state} /></div>
      <DataGrid rows={items} columns={columns} rowKey={(w) => w.ticker} state={state} selected={sel} onSelect={pick} onOpen={pick} />
    </>
  );
}

function Detail({ w, onClose }: { w: WatchItem; onClose: () => void }) {
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
        <ChartPanel ticker={w.ticker} watch={w} height={300} compactHead />
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
            <button className="btn sm ghost" onClick={() => { if (confirm(`Stop tracking ${w.name}? Its stored minute bars are kept.`)) m.remove.mutate(w.ticker, { onSuccess: onClose }); }}><Icon name="trash" className="xs" />Remove</button>
          </div>
          <div className="xs faint">Added {when(w.added)}{isNum(w.added_price) ? ` at ${num(w.added_price)}` : ""} · {w.sector} · <Link to={`/markets?t=${encodeURIComponent(w.ticker)}`}>Open in Markets</Link></div>
        </div>
      </div>
    </aside>
  );
}

function AddCompany({ count }: { count: number }) {
  const [text, setText] = useState("");
  const [sector, setSector] = useState("");
  const s = useLiveSearch(text);
  const sectors = useSectors();
  const m = useWatchMutations();
  const app = useApp();
  const add = (ticker: string, name?: string, sec?: string, cap?: string, close?: () => void) =>
    m.add.mutate({ ticker, name, sector: sec || sector || undefined, cap }, {
      onSuccess: () => { app.toast(`Tracking ${name ?? ticker}`, "ok"); setText(""); close?.(); },
      onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
    });
  return (
    <Popover className="pop" trigger={(open, toggle) => <button className={`btn ${open ? "on" : ""}`} onClick={toggle} disabled={count >= 60}><Icon name="add" className="sm" />Add company</button>}>
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

function EmptyWatch() {
  const companies = useCompanies();
  const m = useWatchMutations();
  const app = useApp();
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const list = (companies.data ?? []).filter((c) => c.ticker);
  const addAll = async () => {
    setBusy(true);
    try {
      for (const c of list.slice(0, 60)) await api.post("/api/watchlist", { ticker: c.ticker, name: c.name, sector: c.sector, cap: c.cap });
      app.toast(`Tracking ${Math.min(60, list.length)} companies`, "ok");
    } catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); }
    finally { setBusy(false); qc.invalidateQueries({ queryKey: ["watchlist"] }); m.poll.mutate(); }
  };
  return (
    <Panel>
      <Empty icon="eye" title="Nothing tracked yet" action={<div className="row">{list.length > 0 && <button className="btn" onClick={addAll} disabled={busy}><Icon name={busy ? "loading" : "add"} className={`sm ${busy ? "spin" : ""}`} />Track my {list.length} companies</button>}<Link className="btn sec" to="/markets">Find companies in Markets</Link></div>}>
        Add companies to follow their price live. While the market is open the tracker polls every 30 seconds, stores every minute bar on this computer, re-values covered companies at the live price, and alerts you on the levels you set.
      </Empty>
    </Panel>
  );
}

function AlertsPanel() {
  const q = useLiveAlerts();
  const qc = useQueryClient();
  const unseen = (q.data ?? []).filter((a) => !a.seen).length;
  const ICON: Record<string, string> = { below: "arrow-down", above: "arrow-up", buy_below: "tag", move: "pulse" };
  return (
    <Panel title="Live alerts" meta={unseen ? `${unseen} new` : "price levels, buy-below crossings and big daily moves"}
      tools={unseen > 0 && <button className="btn xs ghost" onClick={() => api.post("/api/live/alerts/seen").then(() => qc.invalidateQueries({ queryKey: ["live-alerts"] }))}>Mark all read</button>} flush>
      {q.isError ? <div style={{ padding: 12 }}><ErrorNote error={q.error} /></div> : !(q.data ?? []).length ? (
        <div className="empty" style={{ padding: 24 }}><Icon name="bell" /><span className="small">No alerts yet.</span></div>
      ) : (
        <div className="feed" style={{ maxHeight: 260 }}>
          {q.data!.slice(0, 50).map((a) => (
            <div key={a.id} className={`ev ${a.seen ? "" : "new"}`}>
              <span className="ic"><Icon name={ICON[a.kind] ?? "bell"} className={`sm ${a.kind === "below" || a.kind === "buy_below" ? "up" : a.kind === "above" ? "warn" : "info"}`} /></span>
              <div className="grow"><div className="t">{a.message}</div><div className="d">{when(a.t)} · session {a.session}</div></div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
