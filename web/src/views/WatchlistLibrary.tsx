import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useCompanies, useStartJob, useStatus } from "../lib/hooks";
import { Company } from "../lib/api";
import { isOpen, useLiveSearch, useWatchlist, useWatchlistMutations, useWatchlists, WatchItem, WatchList } from "../lib/live";
import { normName, useScope } from "../lib/scope";
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

type Start = "empty" | "pick" | "import" | "coverage" | "sector" | "copy";
type Entry = { ticker: string; name?: string; sector?: string; cap?: string };

const TICKER = /^[A-Z0-9&-]{1,20}(\.(NS|BO))?$/;
/** split one CSV line, keeping commas inside quotes */
const cells = (line: string) => line.split(/[,;\t](?=(?:[^"]*"[^"]*")*[^"]*$)/).map((c) => c.trim().replace(/^"|"$/g, "").trim());

/**
 * Companies from a pasted or uploaded list: a CSV with a ticker/symbol and/or a
 * name column, or simply tickers and names separated by lines or commas. Names
 * are matched against the universe; anything else that looks like an NSE or
 * BSE symbol is taken as one.
 */
export function parseCompanies(text: string, universe: Company[]): { found: Entry[]; missed: string[] } {
  const byTicker = new Map(universe.filter((c) => c.ticker).map((c) => [c.ticker.toUpperCase().split(".")[0], c]));
  const byName = new Map(universe.map((c) => [normName(c.name), c]));
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const head = lines.length ? cells(lines[0]).map((h) => h.toLowerCase()) : [];
  const ti = head.findIndex((h) => /ticker|symbol|nse|code/.test(h));
  const ni = head.findIndex((h) => /name|company/.test(h));
  const si = head.findIndex((h) => /sector|industry/.test(h));
  const rows: { ticker?: string; name?: string; sector?: string }[] = ti >= 0 || ni >= 0
    ? lines.slice(1).map((l) => { const c = cells(l); return { ticker: ti >= 0 ? c[ti] : undefined, name: ni >= 0 ? c[ni] : undefined, sector: si >= 0 ? c[si] : undefined }; })
    : text.split(/[\r\n,;\t]+/).map((t) => t.trim().replace(/^"|"$/g, "")).filter(Boolean).map((t) => (TICKER.test(t.toUpperCase()) && !/\s/.test(t) ? { ticker: t } : { name: t }));
  const found = new Map<string, Entry>(), missed: string[] = [];
  for (const r of rows) {
    const t = (r.ticker ?? "").toUpperCase().replace(/\s/g, "");
    const known = (t && byTicker.get(t.split(".")[0])) || (r.name && byName.get(normName(r.name)));
    if (known && known.ticker) found.set(known.ticker, { ticker: known.ticker, name: known.name, sector: known.sector, cap: known.cap });
    else if (t && TICKER.test(t)) { const tk = t.includes(".") ? t : `${t}.NS`; found.set(tk, { ticker: tk, name: r.name || undefined, sector: r.sector || undefined }); }
    else if (r.name || r.ticker) missed.push(r.name || r.ticker || "");
  }
  return { found: [...found.values()], missed };
}

/** Create a watchlist: name, notes, colour, and what it starts with. */
export function ListEditor({ onClose }: { onClose: () => void }) {
  const lib = useWatchlists();
  const companies = useCompanies();
  const lm = useWatchlistMutations();
  const app = useApp();
  const nav = useNavigate();
  const colors = lib.data?.colors ?? ["#3994bc"];
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [color, setColor] = useState(colors[(lib.data?.lists.length ?? 0) % colors.length]);
  const [start, setStart] = useState<Start>("empty");
  const [sector, setSector] = useState("");
  const [copyOf, setCopyOf] = useState("");
  const [picks, setPicks] = useState<Entry[]>([]);
  const [find, setFind] = useState("");
  const [paste, setPaste] = useState("");
  const [fileName, setFileName] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const hits = useLiveSearch(start === "pick" ? find : "");
  const universe = companies.data ?? [];
  const covered = universe.filter((c) => c.ticker);
  const sectors = [...new Set(covered.map((c) => c.sector).filter(Boolean))].sort();
  const imported = useMemo(() => (start === "import" && paste.trim() ? parseCompanies(paste, universe) : { found: [], missed: [] }), [start, paste, universe]);
  const busy = lm.create.isPending;
  const startWith = (): Entry[] => {
    if (start === "pick") return picks;
    if (start === "import") return imported.found;
    if (start === "coverage") return covered.map((c) => ({ ticker: c.ticker, name: c.name, sector: c.sector, cap: c.cap }));
    if (start === "sector") return covered.filter((c) => c.sector === sector).map((c) => ({ ticker: c.ticker, name: c.name, sector: c.sector, cap: c.cap }));
    if (start === "copy") return (lib.data?.lists.find((l) => l.id === copyOf)?.companies ?? []).map((c) => ({ ticker: c.ticker, name: c.name, sector: c.sector }));
    return [];
  };
  const startCount = startWith().length;
  const room = (lib.data?.max_tracked ?? 100) - (lib.data?.tracked ?? 0);
  const save = async () => {
    try {
      const want = startWith();
      const made = await lm.create.mutateAsync({ name: name.trim(), description: desc.trim(), color, tickers: want });
      app.toast(`“${made.name}” created${made.count ? ` with ${made.count} compan${made.count === 1 ? "y" : "ies"}` : ""}${made.count < want.length ? ` · ${want.length - made.count} could not be added` : ""}`, made.count < want.length ? "info" : "ok");
      onClose();
      nav(`/watchlist/${encodeURIComponent(made.id)}`);
    } catch (e) { app.toast(err(e), "error"); }
  };
  const addPick = (r: Entry) => { setPicks((p) => (p.some((x) => x.ticker === r.ticker) ? p : [...p, r])); setFind(""); };
  const readFile = async (f: File) => { setFileName(f.name); setPaste(await f.text()); };
  const blocked = busy || !name.trim() || (start === "sector" && !sector) || (start === "copy" && !copyOf) || ((start === "pick" || start === "import") && !startCount);
  return (
    <Drawer title="New watchlist" icon="add" onClose={onClose}
      footer={<><span className="xs faint">{startCount ? `${startCount} compan${startCount === 1 ? "y" : "ies"} to add` : ""}</span><span className="spacer" /><button className="btn sec" onClick={onClose}>Cancel</button>
        <button className="btn" disabled={blocked} onClick={save}>
          <Icon name={busy ? "loading" : "check"} className={`sm ${busy ? "spin" : ""}`} />Create</button></>}>
      <div className="col" style={{ gap: 14 }}>
        <label className="fld"><span>Name</span><input className="inp" autoFocus maxLength={60} value={name} placeholder="e.g. Defence ideas" onChange={(e) => setName(e.target.value)} /></label>
        <label className="fld"><span>Description</span><textarea className="inp" rows={2} maxLength={400} value={desc} placeholder="What this list is for: a theme, a strategy, a shortlist to research…" onChange={(e) => setDesc(e.target.value)} /></label>
        <div className="fld"><span>Colour</span>
          <div className="wl-colors">{colors.map((c) => <button key={c} className={c === color ? "on" : ""} style={{ background: c }} onClick={() => setColor(c)} title={c} aria-label={`Colour ${c}`} />)}</div>
        </div>
        <div className="fld"><span>Start with</span>
          <div className="wl-start">
            {([
              ["empty", "add", "An empty list", "add companies later"],
              ["pick", "search", "Pick companies", "search and add them one by one"],
              ["import", "cloud-upload", "Import a list", "a CSV or text file, or paste"],
              ["coverage", "table", "Every covered company", `${covered.length} in your universe`],
              ["sector", "symbol-class", "One sector", "its covered companies"],
              ["copy", "copy", "A copy of a list", "same companies, new name"],
            ] as [Start, string, string, string][]).map(([k, ic, l, d]) => (
              <button key={k} className={start === k ? "on" : ""} onClick={() => setStart(k)} aria-pressed={start === k}>
                <Icon name={ic} className="sm" /><b>{l}</b><span>{d}</span>
              </button>
            ))}
          </div>
        </div>

        {start === "pick" && (
          <div className="wl-pick">
            <div className="search"><Icon name="search" /><input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Company name or NSE symbol" autoFocus /></div>
            {find.trim() && (
              <div className="wl-pick-hits">
                {(hits.data ?? []).slice(0, 8).map((r) => (
                  <button key={r.ticker} onClick={() => addPick({ ticker: r.ticker, name: r.lookup ? undefined : r.name, sector: r.lookup ? undefined : r.sector, cap: r.cap })}
                    disabled={picks.some((x) => x.ticker === r.ticker)}>
                    <Icon name={picks.some((x) => x.ticker === r.ticker) ? "check" : r.lookup ? "globe" : "add"} className="sm" />
                    <span className="grow ellipsis">{r.lookup ? `Add ${r.ticker}` : shortName(r.name)}</span>
                    <span className="mono xs faint">{r.lookup ? "new symbol" : r.ticker}</span>
                  </button>
                ))}
                {hits.isFetching && !hits.data?.length && <span className="xs faint" style={{ padding: 8 }}>Searching…</span>}
                {!hits.isFetching && hits.data && !hits.data.length && <span className="xs faint" style={{ padding: 8 }}>Nothing found for “{find}”.</span>}
              </div>
            )}
            <div className="wl-chips">
              {picks.map((p) => <span key={p.ticker} className="wl-chip-x">{p.name ? shortName(p.name) : p.ticker}<button onClick={() => setPicks(picks.filter((x) => x.ticker !== p.ticker))} title="Remove" aria-label={`Remove ${p.ticker}`}><Icon name="close" className="xs" /></button></span>)}
              {!picks.length && <span className="xs faint">No companies picked yet.</span>}
            </div>
          </div>
        )}

        {start === "import" && (
          <div className="wl-pick">
            <input ref={file} type="file" accept=".csv,.txt,text/csv,text/plain" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) readFile(f); e.target.value = ""; }} />
            <div className="row" style={{ gap: 8 }}>
              <button className="btn sm sec" onClick={() => file.current?.click()}><Icon name="cloud-upload" className="sm" />Choose a file</button>
              {fileName && <span className="xs mono faint ellipsis">{fileName}</span>}
              <span className="spacer" />
              {paste && <button className="btn sm ghost" onClick={() => { setPaste(""); setFileName(""); }}>Clear</button>}
            </div>
            <textarea className="inp mono" rows={6} value={paste} onChange={(e) => { setPaste(e.target.value); setFileName(""); }}
              placeholder={"…or paste here: one per line or comma-separated\nTCS, INFY.NS, HDFCBANK\nHindustan Aeronautics\n\nA CSV with a ticker or name column works too (the Universe export)."} />
            {paste.trim() && (
              <div className="wl-import-r">
                <span className={imported.found.length ? "up" : "faint"}><Icon name="pass" className="xs" />{imported.found.length} recognised</span>
                {imported.missed.length > 0 && <span className="warn" title={imported.missed.join(", ")}><Icon name="warning" className="xs" />{imported.missed.length} not recognised: {imported.missed.slice(0, 3).join(", ")}{imported.missed.length > 3 ? "…" : ""}</span>}
              </div>
            )}
            {imported.found.length > 0 && (
              <div className="wl-chips">
                {imported.found.slice(0, 24).map((p) => <span key={p.ticker} className="wl-chip-x" title={p.ticker}>{p.name ? shortName(p.name) : p.ticker}</span>)}
                {imported.found.length > 24 && <span className="xs faint">+{imported.found.length - 24} more</span>}
              </div>
            )}
          </div>
        )}

        {start === "sector" && <select className="sel" value={sector} onChange={(e) => setSector(e.target.value)}><option value="">Choose a sector…</option>{sectors.map((x) => <option key={x}>{x}</option>)}</select>}
        {start === "copy" && <select className="sel" value={copyOf} onChange={(e) => setCopyOf(e.target.value)}><option value="">Choose a list…</option>{(lib.data?.lists ?? []).map((l) => <option key={l.id} value={l.id}>{l.name} ({l.count})</option>)}</select>}
        {startCount > 0 && <span className="xs faint">{startCount} compan{startCount === 1 ? "y" : "ies"} will be added{startCount > room ? ` · only ${Math.max(0, room)} more can be tracked (${lib.data?.max_tracked ?? 100} across every list), unless they are already on another list` : ""}. You can add more from the list's page.</span>}
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
