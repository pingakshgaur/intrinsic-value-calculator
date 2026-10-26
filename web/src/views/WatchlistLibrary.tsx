import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useCompanies, useStartJob, useStatus } from "../lib/hooks";
import { isOpen, useWatchlist, useWatchlistMutations, useWatchlists, WatchItem, WatchList } from "../lib/live";
import { useScope } from "../lib/scope";
import { ago, isNum, pct, shortName } from "../lib/format";
import { Drawer, Empty, Icon, PageHeader, Panel, Popover, QueryView } from "../components/ui";
import { useApp } from "../components/workbenchContext";

const err = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Every watchlist, as cards: create, open, edit, copy, focus the app on one, delete. */
export function Watchlist() {
  const q = useWatchlists();
  const all = useWatchlist();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [find, setFind] = useState("");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<WatchList | null>(null);

  // links from alerts (/watchlist?t=HAL.NS) open the first list holding that company
  const t = params.get("t");
  useEffect(() => {
    if (!t || !q.data) return;
    const hit = q.data.lists.find((l) => l.tickers.includes(t));
    if (hit) nav(`/watchlist/${encodeURIComponent(hit.id)}?t=${encodeURIComponent(t)}`, { replace: true });
  }, [t, q.data, nav]);

  const quotes = useMemo(() => new Map((all.data?.items ?? []).map((w) => [w.ticker, w])), [all.data]);
  const live = isOpen(all.data?.tracker.market) && !all.data?.tracker.paused;

  return (
    <div className="page">
      <QueryView q={q} rows={8}>
        {(d) => {
          const f = find.trim().toLowerCase();
          const lists = d.lists
            .filter((l) => !f || `${l.name} ${l.description} ${l.companies.map((c) => `${c.name} ${c.ticker}`).join(" ")}`.toLowerCase().includes(f))
            .sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned) || b.updated - a.updated);
          return (
            <>
              <PageHeader crumbs={[{ label: "Analysis" }, { label: "Watchlists" }]} title="Watchlists"
                sub={<span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <span className={`live-dot ${live ? "on" : ""}`}>{all.data?.tracker.paused ? "Tracking paused" : live ? "Tracking live" : "Market closed"}</span>
                  <span>{d.lists.length} list{d.lists.length === 1 ? "" : "s"} · {d.tracked} of {d.max_tracked} companies tracked</span>
                </span>}
                actions={<>
                  <div className="search sm" style={{ width: 220 }}><Icon name="search" /><input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find a list or company" /></div>
                  <button className="btn" onClick={() => setCreating(true)}><Icon name="add" className="sm" />New watchlist</button>
                </>} />
              <div className="wl-lib">
                {lists.map((l) => <ListCard key={l.id} l={l} quotes={quotes} onEdit={() => setEditing(l)} />)}
                {!f && (
                  <button className="wl-card new" onClick={() => setCreating(true)}>
                    <Icon name="add" />
                    <b>New watchlist</b>
                    <span className="xs faint">For a theme, a sector, a strategy or a shortlist</span>
                  </button>
                )}
              </div>
              {f && !lists.length && <Panel><Empty icon="search" title="No list matches">Nothing named or holding “{find}”.</Empty></Panel>}
            </>
          );
        }}
      </QueryView>
      {creating && <ListEditor onClose={() => setCreating(false)} />}
      {editing && <ListEditor list={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ListCard({ l, quotes, onEdit }: { l: WatchList; quotes: Map<string, WatchItem>; onEdit: () => void }) {
  const nav = useNavigate();
  const scope = useScope();
  const lm = useWatchlistMutations();
  const app = useApp();
  const rows = l.tickers.map((t) => quotes.get(t)).filter(Boolean) as WatchItem[];
  const ch = rows.map((w) => w.quote?.chg_pct).filter(isNum) as number[];
  const up = ch.filter((x) => x > 0).length, down = ch.filter((x) => x < 0).length;
  const avg = ch.length ? ch.reduce((a, b) => a + b, 0) / ch.length : null;
  const cheap = rows.filter((w) => w.quote?.hm?.buy_below && isNum(w.quote.last) && w.quote.last <= w.quote.hm.buy_below).length;
  const open = () => nav(`/watchlist/${encodeURIComponent(l.id)}`);
  const focused = scope.id === l.id;
  return (
    <div className={`wl-card ${focused ? "focused" : ""}`} style={{ ["--wc" as string]: l.color }} onClick={open} role="link" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && open()}>
      <div className="wl-card-h">
        <i className="wl-sw" />
        <b className="ellipsis" title={l.name}>{l.name}</b>
        {l.pinned && <Icon name="pinned" className="xs" title="Pinned" />}
        <span className="spacer" />
        <div onClick={(e) => e.stopPropagation()}>
          <Popover className="menu" trigger={(o, toggle) => <button className={`ibtn sm ${o ? "on" : ""}`} onClick={toggle} title="More"><Icon name="ellipsis" /></button>}>
            {(close) => (
              <>
                <button onClick={() => { close(); open(); }}><Icon name="go-to-file" className="sm" />Open</button>
                <button onClick={() => { close(); onEdit(); }}><Icon name="edit" className="sm" />Edit name, notes, companies</button>
                <button onClick={() => { close(); scope.set(focused ? null : l.id); }}><Icon name="target" className="sm" />{focused ? "Stop focusing the app" : "Focus the app on this list"}</button>
                <button onClick={() => { close(); lm.edit.mutate({ id: l.id, pinned: !l.pinned }); }}><Icon name={l.pinned ? "pinned-dirty" : "pin"} className="sm" />{l.pinned ? "Unpin" : "Pin to the top"}</button>
                <button onClick={() => { close(); lm.duplicate.mutate({ id: l.id }, { onSuccess: (c) => app.toast(`Copied as “${c.name}”`, "ok"), onError: (e) => app.toast(err(e), "error") }); }}><Icon name="copy" className="sm" />Duplicate</button>
                <hr />
                <button onClick={() => { close(); if (confirm(`Delete “${l.name}”? Companies on other lists stay tracked.`)) lm.remove.mutate(l.id, { onSuccess: () => app.toast(`“${l.name}” deleted`, "ok"), onError: (e) => app.toast(err(e), "error") }); }}><Icon name="trash" className="sm" />Delete</button>
              </>
            )}
          </Popover>
        </div>
      </div>
      <p className="wl-card-d">{l.description || <span className="faint">No description</span>}</p>
      <div className="wl-card-co">
        {l.companies.slice(0, 6).map((c) => <span key={c.ticker} title={c.name}>{shortName(c.name)}</span>)}
        {l.count > 6 && <span className="faint">+{l.count - 6}</span>}
        {!l.count && <span className="faint">No companies yet</span>}
      </div>
      <div className="wl-card-f">
        <div><b>{l.count}</b><span>companies</span></div>
        <div><b>{up}<span className="faint"> / </span>{down}</b><span>up / down</span></div>
        <div><b className={isNum(avg) ? (avg >= 0 ? "up" : "down") : ""}>{pct(avg, 2, true)}</b><span>avg change</span></div>
        <div><b className={cheap ? "up" : ""}>{cheap}</b><span title="Trading below the buy-below price">buy zone</span></div>
      </div>
      <div className="wl-card-b">
        <span className="xs faint">Updated {ago(l.updated)}</span>
        <span className="spacer" />
        {focused && <span className="tag xs" title="The app shows only this list's companies">focused</span>}
      </div>
    </div>
  );
}

type Start = "empty" | "coverage" | "sector" | "copy";

/** Create a watchlist, or edit one: name, notes, colour, and its companies. */
export function ListEditor({ list, onClose }: { list?: WatchList; onClose: () => void }) {
  const lib = useWatchlists();
  const companies = useCompanies();
  const lm = useWatchlistMutations();
  const app = useApp();
  const nav = useNavigate();
  const colors = lib.data?.colors ?? ["#3994bc"];
  const [name, setName] = useState(list?.name ?? "");
  const [desc, setDesc] = useState(list?.description ?? "");
  const [color, setColor] = useState(list?.color ?? colors[(lib.data?.lists.length ?? 0) % colors.length]);
  const [start, setStart] = useState<Start>("empty");
  const [sector, setSector] = useState("");
  const [copyOf, setCopyOf] = useState("");
  const [order, setOrder] = useState<string[]>(list?.tickers ?? []);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const covered = (companies.data ?? []).filter((c) => c.ticker);
  const sectors = [...new Set(covered.map((c) => c.sector).filter(Boolean))].sort();
  const busy = lm.create.isPending || lm.edit.isPending;
  const startWith = (): { ticker: string; name?: string; sector?: string; cap?: string }[] => {
    if (start === "coverage") return covered.map((c) => ({ ticker: c.ticker, name: c.name, sector: c.sector, cap: c.cap }));
    if (start === "sector") return covered.filter((c) => c.sector === sector).map((c) => ({ ticker: c.ticker, name: c.name, sector: c.sector, cap: c.cap }));
    if (start === "copy") return (lib.data?.lists.find((l) => l.id === copyOf)?.companies ?? []).map((c) => ({ ticker: c.ticker, name: c.name, sector: c.sector }));
    return [];
  };
  const startCount = startWith().length;
  const save = async () => {
    try {
      if (!list) {
        const made = await lm.create.mutateAsync({ name: name.trim(), description: desc.trim(), color, tickers: startWith() });
        app.toast(`“${made.name}” created${made.count ? ` with ${made.count} companies` : ""}`, "ok");
        onClose();
        nav(`/watchlist/${encodeURIComponent(made.id)}`);
        return;
      }
      await lm.edit.mutateAsync({ id: list.id, name: name.trim(), description: desc.trim(), color, tickers: order.filter((t) => !gone.has(t)) });
      for (const t of gone) await lm.removeOne(list.id, t);
      app.toast(`“${name.trim()}” saved`, "ok");
      onClose();
    } catch (e) { app.toast(err(e), "error"); }
  };
  const move = (i: number, d: number) => { const l = [...order]; const j = i + d; if (j < 0 || j >= l.length) return; [l[i], l[j]] = [l[j], l[i]]; setOrder(l); };
  const byTicker = new Map((list?.companies ?? []).map((c) => [c.ticker, c]));
  return (
    <Drawer title={list ? `Edit “${list.name}”` : "New watchlist"} icon={list ? "edit" : "add"} onClose={onClose}
      footer={<><span className="spacer" /><button className="btn sec" onClick={onClose}>Cancel</button>
        <button className="btn" disabled={busy || !name.trim() || (start === "sector" && !sector) || (start === "copy" && !copyOf)} onClick={save}>
          <Icon name={busy ? "loading" : "check"} className={`sm ${busy ? "spin" : ""}`} />{list ? "Save" : "Create"}</button></>}>
      <div className="col" style={{ gap: 14 }}>
        <label className="fld"><span>Name</span><input className="inp" autoFocus maxLength={60} value={name} placeholder="e.g. Defence ideas" onChange={(e) => setName(e.target.value)} /></label>
        <label className="fld"><span>Description</span><textarea className="inp" rows={3} maxLength={400} value={desc} placeholder="What this list is for: a theme, a strategy, a shortlist to research…" onChange={(e) => setDesc(e.target.value)} /></label>
        <div className="fld"><span>Colour</span>
          <div className="wl-colors">{colors.map((c) => <button key={c} className={c === color ? "on" : ""} style={{ background: c }} onClick={() => setColor(c)} title={c} aria-label={`Colour ${c}`} />)}</div>
        </div>
        {!list ? (
          <div className="fld"><span>Start with</span>
            <div className="col" style={{ gap: 6 }}>
              {([["empty", "An empty list"], ["coverage", `Every covered company (${covered.length})`], ["sector", "The covered companies of one sector"], ["copy", "A copy of another list"]] as [Start, string][]).map(([k, l]) => (
                <label key={k} className="wl-radio"><input type="radio" name="start" checked={start === k} onChange={() => setStart(k)} />{l}</label>
              ))}
              {start === "sector" && <select className="sel sm" value={sector} onChange={(e) => setSector(e.target.value)}><option value="">Choose a sector…</option>{sectors.map((x) => <option key={x}>{x}</option>)}</select>}
              {start === "copy" && <select className="sel sm" value={copyOf} onChange={(e) => setCopyOf(e.target.value)}><option value="">Choose a list…</option>{(lib.data?.lists ?? []).map((l) => <option key={l.id} value={l.id}>{l.name} ({l.count})</option>)}</select>}
              {start !== "empty" && <span className="xs faint">{startCount} compan{startCount === 1 ? "y" : "ies"} will be added. You can add more from the list's page.</span>}
            </div>
          </div>
        ) : (
          <div className="fld"><span>Companies · {order.length - gone.size} <span className="faint">(order is the list's default order)</span></span>
            <div className="wl-edit-co">
              {order.map((t, i) => (
                <div key={t} className={gone.has(t) ? "gone" : ""}>
                  <span className="grow ellipsis">{byTicker.get(t)?.name ?? t}<span className="mono xs faint"> {t}</span></span>
                  <button className="ibtn sm" onClick={() => move(i, -1)} disabled={i === 0} title="Earlier"><Icon name="arrow-up" className="xs" /></button>
                  <button className="ibtn sm" onClick={() => move(i, 1)} disabled={i === order.length - 1} title="Later"><Icon name="arrow-down" className="xs" /></button>
                  <button className="ibtn sm" onClick={() => setGone((g) => { const n = new Set(g); if (n.has(t)) n.delete(t); else n.add(t); return n; })} title={gone.has(t) ? "Keep it" : "Take it off this list"}>
                    <Icon name={gone.has(t) ? "discard" : "close"} className="xs" /></button>
                </div>
              ))}
              {!order.length && <span className="xs faint" style={{ padding: 8 }}>No companies yet - add them from the list's page.</span>}
            </div>
          </div>
        )}
      </div>
    </Drawer>
  );
}

/** Research run on a list's covered companies. */
export function ResearchList({ list }: { list: WatchList }) {
  const companies = useCompanies();
  const start = useStartJob();
  const status = useStatus();
  const app = useApp();
  const covered = new Set((companies.data ?? []).map((c) => (c.ticker || "").toUpperCase().split(".")[0]));
  const tickers = list.tickers.map((t) => t.toUpperCase().split(".")[0]).filter((t) => covered.has(t) && /^[A-Z0-9&._-]+$/.test(t));
  const busy = !!status.data?.active_job || start.isPending;
  const go = (quick: boolean) => start.mutate({ kind: "agents", options: { quick, tickers: tickers.join(",") } }, {
    onSuccess: (j) => { app.toast(`Researching ${tickers.length} companies from “${list.name}”`, "ok"); app.showJob(j.id); },
    onError: (e) => app.toast(err(e), "error"),
  });
  return (
    <Popover className="menu" trigger={(o, toggle) => (
      <button className={`btn sec ${o ? "on" : ""}`} onClick={toggle} disabled={busy || !tickers.length}
        title={!tickers.length ? "None of this list's companies is in Coverage, so the agents cannot research them yet" : busy ? "Another run is in progress" : `Research the ${tickers.length} covered companies on this list`}>
        <Icon name="rocket" className="sm" />Research<Icon name="chevron-down" className="xs" />
      </button>
    )}>
      {(close) => (
        <>
          <div className="label" style={{ padding: "6px 10px 4px" }}>{tickers.length} of {list.count} companies are covered</div>
          <button onClick={() => { close(); go(true); }}><Icon name="zap" className="sm" />Quick sweep (news and market)</button>
          <button onClick={() => { close(); go(false); }}><Icon name="rocket" className="sm" />Full research (all 23 agents)</button>
          {tickers.length < list.count && <Link to="/universe" className="menu-note xs" onClick={close}>Add the others to Coverage on the Universe page</Link>}
        </>
      )}
    </Popover>
  );
}
