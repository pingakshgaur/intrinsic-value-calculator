import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { isOpen, useWatchlist, useWatchlistMutations, useWatchlists, WatchItem, WatchList } from "../lib/live";
import { useScope } from "../lib/scope";
import { CompanyImporter, Entry } from "../components/CompanyImporter";
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
                {lists.map((l) => <ListCard key={l.id} l={l} quotes={quotes} onEdit={() => nav(`/watchlist/${encodeURIComponent(l.id)}?edit=1`)} />)}
                {!f && !d.lists.length && (
                  <button className="wl-card new" onClick={() => setCreating(true)}>
                    <Icon name="add" />
                    <b>New watchlist</b>
                    <span className="xs faint">For a theme, a sector, a strategy or a shortlist — add companies by name, by sector or from a spreadsheet</span>
                  </button>
                )}
              </div>
              {f && !lists.length && <Panel><Empty icon="search" title="No list matches">Nothing named or holding “{find}”.</Empty></Panel>}
            </>
          );
        }}
      </QueryView>
      {creating && <ListEditor onClose={() => setCreating(false)} />}
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

/** Create a watchlist: name, notes, colour, and - optionally - its first companies, picked any of four ways. */
export function ListEditor({ onClose }: { onClose: () => void }) {
  const lib = useWatchlists();
  const lm = useWatchlistMutations();
  const app = useApp();
  const nav = useNavigate();
  const colors = lib.data?.colors ?? ["#3994bc"];
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [color, setColor] = useState(colors[(lib.data?.lists.length ?? 0) % colors.length]);
  const [picks, setPicks] = useState<Entry[]>([]);
  const busy = lm.create.isPending;
  const room = (lib.data?.max_tracked ?? 250) - (lib.data?.tracked ?? 0);
  const save = async () => {
    try {
      const made = await lm.create.mutateAsync({ name: name.trim(), description: desc.trim(), color, tickers: picks });
      app.toast(`“${made.name}” created${made.count ? ` with ${made.count} compan${made.count === 1 ? "y" : "ies"}` : ""}${made.count < picks.length ? ` · ${picks.length - made.count} could not be added` : ""}`, made.count < picks.length ? "info" : "ok");
      onClose();
      nav(`/watchlist/${encodeURIComponent(made.id)}`);
    } catch (e) { app.toast(err(e), "error"); }
  };
  return (
    <Drawer title="New watchlist" icon="add" wide onClose={onClose}
      footer={<><span className="xs faint">{picks.length ? `${picks.length} compan${picks.length === 1 ? "y" : "ies"} will be added` : "You can also add companies later"}</span><span className="spacer" /><button className="btn sec" onClick={onClose}>Cancel</button>
        <button className="btn" disabled={busy || !name.trim()} onClick={save}>
          <Icon name={busy ? "loading" : "check"} className={`sm ${busy ? "spin" : ""}`} />Create</button></>}>
      <div className="col" style={{ gap: 14 }}>
        <div className="wl-new-meta">
          <label className="fld"><span>Name</span><input className="inp" autoFocus maxLength={60} value={name} placeholder="e.g. Defence ideas" onChange={(e) => setName(e.target.value)} /></label>
          <div className="fld"><span>Colour</span>
            <div className="wl-colors">{colors.map((c) => <button key={c} className={c === color ? "on" : ""} style={{ background: c }} onClick={() => setColor(c)} title={c} aria-label={`Colour ${c}`} />)}</div>
          </div>
        </div>
        <label className="fld"><span>Description</span><textarea className="inp" rows={2} maxLength={400} value={desc} placeholder="What this list is for: a theme, a strategy, a shortlist to research…" onChange={(e) => setDesc(e.target.value)} /></label>
        <div className="fld"><span>Companies</span>
          <CompanyImporter picks={picks} setPicks={setPicks} room={room} />
        </div>
      </div>
    </Drawer>
  );
}
