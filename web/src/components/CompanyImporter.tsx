import { useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { DirectoryCompany, IndexMembers, useDirectory, useDirectorySectors, useIndexCatalog, useIndexMatch, useIndexMembers, useLiveSearch, useWatchlists } from "../lib/live";
import { normName } from "../lib/scope";
import { ago, shortName } from "../lib/format";
import { Icon } from "./ui";
import { useApp } from "./workbenchContext";

export type Entry = { ticker: string; name?: string; sector?: string; cap?: string };
type Way = "search" | "indices" | "sectors" | "file" | "list";

const TICKER = /^[A-Z0-9&-]{1,20}(\.(NS|BO))?$/;
/** split one CSV line, keeping commas inside quotes */
const cells = (line: string) => line.split(/[,;\t](?=(?:[^"]*"[^"]*")*[^"]*$)/).map((c) => c.trim().replace(/^"|"$/g, "").trim());
const entry = (c: { ticker: string; name?: string; sector?: string; cap?: string }): Entry => ({ ticker: c.ticker, name: c.name, sector: c.sector || undefined, cap: c.cap || undefined });

/**
 * Companies from a pasted or uploaded list: a CSV with a ticker/symbol and/or a
 * name column, or simply tickers and names separated by lines or commas. Names
 * are matched against every company the app knows; anything else that looks
 * like an NSE or BSE symbol is taken as one.
 */
export function parseCompanies(text: string, universe: { ticker: string; name: string; sector: string; cap: string }[]): { found: Entry[]; missed: string[] } {
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
    if (known && known.ticker) found.set(known.ticker, entry(known));
    else if (t && TICKER.test(t)) { const tk = t.includes(".") ? t : `${t}.NS`; found.set(tk, { ticker: tk, name: r.name || undefined, sector: r.sector || undefined }); }
    else if (r.name || r.ticker) missed.push(r.name || r.ticker || "");
  }
  return { found: [...found.values()], missed };
}

/** The first sheet of an Excel workbook as CSV text. */
async function sheetText(f: File) {
  const { default: ExcelJS } = await import("exceljs");
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.load(await f.arrayBuffer());
  const ws = wb.worksheets[0];
  if (!ws) return "";
  const out: string[] = [];
  ws.eachRow((row) => {
    const vals = (row.values as unknown[]).slice(1).map((v) => {
      const x = v && typeof v === "object" && "text" in (v as object) ? (v as { text: string }).text : v && typeof v === "object" && "result" in (v as object) ? (v as { result: unknown }).result : v;
      const s = x == null ? "" : String(x);
      return /[",;\t]/.test(s) ? `"${s.replace(/"/g, "'")}"` : s;
    });
    out.push(vals.join(","));
  });
  return out.join("\n");
}

/**
 * Add companies to a watchlist five ways: search for them, take a whole index
 * (NIFTY 50, NIFTY 500, large / mid / small cap…) or whole sectors, read a
 * spreadsheet (CSV, Excel or pasted text), or copy another list. The
 * picks collect at the bottom; `taken` are already on the list and greyed out.
 */
export function CompanyImporter({ picks, setPicks, taken, room, exceptList }: {
  picks: Entry[]; setPicks: (p: Entry[]) => void; taken?: Set<string>; room?: number; exceptList?: string;
}) {
  const [way, setWay] = useState<Way>("search");
  const [index, setIndex] = useState<string | null>(null);
  const has = useMemo(() => new Set(picks.map((p) => p.ticker)), [picks]);
  const add = (es: Entry[]) => { const seen = new Set(has); const more = es.filter((e) => !seen.has(e.ticker) && !taken?.has(e.ticker) && seen.add(e.ticker)); if (more.length) setPicks([...picks, ...more]); };
  const drop = (tickers: string[]) => { const t = new Set(tickers); setPicks(picks.filter((p) => !t.has(p.ticker))); };
  const ways: [Way, string, string][] = [["search", "search", "Search"], ["indices", "graph-line", "Indices"], ["sectors", "symbol-class", "Sectors"], ["file", "table", "Spreadsheet"], ["list", "copy", "Another list"]];
  return (
    <div className="imp">
      <div className="seg imp-ways" role="tablist">
        {ways.map(([k, ic, l]) => <button key={k} role="tab" aria-selected={way === k} className={way === k ? "on" : ""} onClick={() => setWay(k)}><Icon name={ic} className="xs" />{l}</button>)}
      </div>
      <div className="imp-body">
        {way === "search" && <Search has={has} taken={taken} add={add} openIndex={(k) => { setIndex(k); setWay("indices"); }} />}
        {way === "indices" && <Indices has={has} taken={taken} add={add} drop={drop} chosen={index} choose={setIndex} />}
        {way === "sectors" && <Sectors has={has} taken={taken} add={add} drop={drop} />}
        {way === "file" && <Sheet add={add} />}
        {way === "list" && <FromList add={add} exceptList={exceptList} />}
      </div>
      <div className="imp-picks">
        <div className="row" style={{ gap: 8 }}>
          <b className="small">{picks.length ? `${picks.length} compan${picks.length === 1 ? "y" : "ies"} to add` : "Nothing picked yet"}</b>
          {room != null && picks.length > room && <span className="xs warn">only {Math.max(0, room)} more can be tracked across every list</span>}
          <span className="spacer" />
          {picks.length > 0 && <button className="btn xs ghost" onClick={() => setPicks([])}>Clear</button>}
        </div>
        {picks.length > 0 && (
          <div className="wl-chips">
            {picks.slice(0, 40).map((p) => <span key={p.ticker} className="wl-chip-x" title={p.ticker}>{p.name ? shortName(p.name) : p.ticker}<button onClick={() => drop([p.ticker])} aria-label={`Remove ${p.ticker}`}><Icon name="close" className="xs" /></button></span>)}
            {picks.length > 40 && <span className="xs faint">+{picks.length - 40} more</span>}
          </div>
        )}
      </div>
    </div>
  );
}

function Search({ has, taken, add, openIndex }: { has: Set<string>; taken?: Set<string>; add: (e: Entry[]) => void; openIndex: (key: string) => void }) {
  const [find, setFind] = useState("");
  const hits = useLiveSearch(find);
  const idx = useIndexMatch(find);
  const qc = useQueryClient();
  const app = useApp();
  const [loading, setLoading] = useState<string | null>(null);
  const indices = idx.data ?? [];
  // "NIFTY50" also looks like a ticker symbol: when it names an index, the index wins
  const rows = (hits.data ?? []).filter((r) => !(r.lookup && indices.length)).slice(0, 10);
  const takeAll = async (key: string, label: string) => {
    setLoading(key);
    try {
      const d = await qc.fetchQuery({ queryKey: ["index", key], queryFn: () => api.get<IndexMembers>(`/api/indices/${encodeURIComponent(key)}`), staleTime: 3_600_000 });
      if (!d.companies.length) { app.toast(d.note || `No companies found for ${label}`, "error"); return; }
      add(d.companies.map(entry));
      app.toast(`${d.companies.length} companies from ${label} picked${d.source !== "nse" && d.note ? ` · ${d.note}` : ""}`, d.source === "nse" ? "ok" : "info");
      setFind("");
    } catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); } finally { setLoading(null); }
  };
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="search"><Icon name="search" /><input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Company, NSE / BSE symbol, or an index: NIFTY 50, Nifty 500, Large cap…" autoFocus /></div>
      {find.trim() ? (
        <div className="wl-pick-hits">
          {indices.map((i) => (
            <div key={i.key} className="imp-idx-hit">
              <button onClick={() => takeAll(i.key, i.label)} disabled={!!loading}>
                <Icon name={loading === i.key ? "loading" : "graph-line"} className={`sm ${loading === i.key ? "spin" : ""}`} />
                <span className="grow ellipsis"><b>{i.label}</b> <span className="faint">· add every company in it</span></span>
                <span className="xs faint">{i.group}</span>
              </button>
              <button className="imp-idx-see" onClick={() => openIndex(i.key)} title={`See the companies in ${i.label} first`}>See list</button>
            </div>
          ))}
          {rows.map((r) => {
            const on = has.has(r.ticker) || !!taken?.has(r.ticker);
            return (
              <button key={r.ticker} onClick={() => { add([{ ticker: r.ticker, name: r.lookup ? undefined : r.name, sector: r.lookup ? undefined : r.sector, cap: r.cap }]); setFind(""); }} disabled={on}>
                <Icon name={on ? "check" : r.lookup ? "globe" : "add"} className="sm" />
                <span className="grow ellipsis">{r.lookup ? `Add ${r.ticker}` : shortName(r.name)}</span>
                <span className="mono xs faint">{taken?.has(r.ticker) ? "on the list" : r.lookup ? "new symbol" : r.ticker}</span>
              </button>
            );
          })}
          {hits.isFetching && !rows.length && !indices.length && <span className="xs faint" style={{ padding: 8 }}>Searching…</span>}
          {!hits.isFetching && hits.data && !rows.length && !indices.length && <span className="xs faint" style={{ padding: 8 }}>Nothing found for “{find}”.</span>}
        </div>
      ) : <span className="xs faint">Type a few letters. A symbol the app has not seen (e.g. ZOMATO) can be added too, and an index name (NIFTY 50, Bank Nifty, Mid cap) brings in all its companies.</span>}
    </div>
  );
}

/** A whole index or size class: NIFTY 50, NIFTY 500, Bank Nifty, large / mid / small cap. */
function Indices({ has, taken, add, drop, chosen, choose }: { has: Set<string>; taken?: Set<string>; add: (e: Entry[]) => void; drop: (t: string[]) => void; chosen: string | null; choose: (k: string | null) => void }) {
  const cat = useIndexCatalog();
  const q = useIndexMembers(chosen);
  const groups = useMemo(() => {
    const g = new Map<string, NonNullable<typeof cat.data>>();
    for (const i of cat.data ?? []) g.set(i.group, [...(g.get(i.group) ?? []), i]);
    return [...g.entries()];
  }, [cat.data]);
  const d = q.data;
  return (
    <div className="col" style={{ gap: 10 }}>
      {groups.map(([g, list]) => (
        <div key={g} className="imp-idx-g">
          <span className="label">{g}</span>
          <div className="imp-sectors">
            {list.map((i) => (
              <button key={i.key} className={`chip ${chosen === i.key ? "on" : ""}`} onClick={() => choose(chosen === i.key ? null : i.key)} aria-pressed={chosen === i.key}>
                {chosen === i.key && <Icon name="check" className="xs" />}{i.label}{i.count != null && <span className="faint">{i.count}</span>}
              </button>
            ))}
          </div>
        </div>
      ))}
      {!cat.data && <span className="xs faint">Loading indices…</span>}
      {chosen && (q.isFetching && !d ? <span className="xs faint row" style={{ gap: 6 }}><Icon name="loading" className="xs spin" />Getting the list from NSE…</span>
        : d && <>
          {d.note && <div className={`note ${d.source === "nse" ? "inf" : "wrn"}`}><Icon name="info" /><div>{d.note}</div></div>}
          <PickList rows={d.companies.map((c) => ({ ...c, lists: [], source: "app" as const }))} has={has} taken={taken} add={add} drop={drop}
            meta={d.source === "nse" && d.fetched ? `NSE list · updated ${ago(d.fetched)}` : undefined} />
        </>)}
    </div>
  );
}

/** A filterable list of companies with "Add all" and a tick per company. */
function PickList({ rows, has, taken, add, drop, loading, meta }: { rows: DirectoryCompany[]; has: Set<string>; taken?: Set<string>; add: (e: Entry[]) => void; drop: (t: string[]) => void; loading?: boolean; meta?: string }) {
  const [find, setFind] = useState("");
  const shown = rows.filter((c) => !find || `${c.name} ${c.ticker} ${c.sector}`.toLowerCase().includes(find.toLowerCase()));
  const free = rows.filter((c) => !taken?.has(c.ticker));
  const allIn = free.length > 0 && free.every((c) => has.has(c.ticker));
  return (
    <div className="imp-list">
      <div className="row" style={{ gap: 8, padding: "6px 8px" }}>
        <div className="search sm grow"><Icon name="search" /><input value={find} onChange={(e) => setFind(e.target.value)} placeholder={`Filter ${rows.length} companies`} /></div>
        {meta && <span className="xs faint">{meta}</span>}
        <button className="btn xs" onClick={() => (allIn ? drop(free.map((c) => c.ticker)) : add(free.map(entry)))} disabled={!free.length}>
          <Icon name={allIn ? "close" : "add"} className="xs" />{allIn ? "Remove all" : `Add all ${free.length}`}</button>
      </div>
      <div className="imp-rows">
        {shown.map((c) => {
          const on = has.has(c.ticker), off = !!taken?.has(c.ticker);
          return (
            <label key={c.ticker} className={`imp-row ${off ? "off" : ""}`}>
              <input type="checkbox" className="cb" checked={on || off} disabled={off} onChange={() => (on ? drop([c.ticker]) : add([entry(c)]))} />
              <span className="grow ellipsis">{shortName(c.name)}</span>
              {c.source === "nse" && <span className="tag xs" title="From NSE's index lists; its accounts are fetched the first time it is valued">new</span>}
              <span className="xs faint ellipsis imp-sec">{c.sector}</span>
              <span className="mono xs faint">{off ? "on the list" : c.ticker.replace(/\.NS$/, "")}</span>
            </label>
          );
        })}
        {loading && !rows.length && <span className="xs faint" style={{ padding: 8 }}>Loading…</span>}
        {!loading && !shown.length && <span className="xs faint" style={{ padding: 8 }}>{rows.length ? "Nothing matches the filter." : "No companies."}</span>}
      </div>
    </div>
  );
}

function Sectors({ has, taken, add, drop }: { has: Set<string>; taken?: Set<string>; add: (e: Entry[]) => void; drop: (t: string[]) => void }) {
  const q = useDirectorySectors();
  const qc = useQueryClient();
  const app = useApp();
  const [chosen, setChosen] = useState<string[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const cos = useDirectory(chosen);
  const rows = (cos.data ?? []).filter((c) => chosen.includes(c.sector || "Unclassified"));
  const refresh = async () => {
    setRefreshing(true);
    try {
      const r = await api.post<{ companies: number }>("/api/directory/refresh");
      app.toast(`Sector lists updated from NSE: ${r.companies} companies`, "ok");
      qc.invalidateQueries({ queryKey: ["directory-sectors"] });
      qc.invalidateQueries({ queryKey: ["directory"] });
    } catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); } finally { setRefreshing(false); }
  };
  const toggle = (s: string) => setChosen(chosen.includes(s) ? chosen.filter((x) => x !== s) : [...chosen, s]);
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="row" style={{ gap: 8 }}>
        <span className="xs faint grow">{q.data ? (q.data.nse_fetched ? `Sectors from the app's lists and NSE's index lists (updated ${ago(q.data.nse_fetched)})` : "Sectors from the companies the app knows. Get the full NSE lists for about 1,000 more companies.") : "Loading sectors…"}</span>
        <button className="btn xs sec" onClick={refresh} disabled={refreshing} title="Download NSE's index lists (Total Market, Nifty 500, Microcap 250) with each company's industry">
          <Icon name={refreshing ? "loading" : "cloud-download"} className={`xs ${refreshing ? "spin" : ""}`} />{q.data?.nse_fetched ? "Update from NSE" : "Get NSE lists"}</button>
      </div>
      <div className="imp-sectors">
        {(q.data?.sectors ?? []).map((s) => (
          <button key={s.sector} className={`chip ${chosen.includes(s.sector) ? "on" : ""}`} onClick={() => toggle(s.sector)} aria-pressed={chosen.includes(s.sector)}>
            {chosen.includes(s.sector) && <Icon name="check" className="xs" />}{s.sector}<span className="faint">{s.count}</span>
          </button>
        ))}
      </div>
      {chosen.length > 0 && <PickList rows={rows} has={has} taken={taken} add={add} drop={drop} loading={cos.isFetching} />}
    </div>
  );
}

function Sheet({ add }: { add: (e: Entry[]) => void }) {
  const everyone = useDirectory("all");
  const app = useApp();
  const file = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const got = useMemo(() => (text.trim() ? parseCompanies(text, everyone.data ?? []) : { found: [], missed: [] }), [text, everyone.data]);
  const read = async (f: File) => {
    setName(f.name);
    try { setText(/\.xlsx?$/i.test(f.name) ? await sheetText(f) : await f.text()); }
    catch (e) { app.toast(`Could not read ${f.name}: ${e instanceof Error ? e.message : String(e)}`, "error"); }
  };
  return (
    <div className="col" style={{ gap: 8 }}>
      <input ref={file} type="file" accept=".csv,.txt,.xlsx,text/csv,text/plain,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden
        onChange={(e) => { const f = e.target.files?.[0]; if (f) read(f); e.target.value = ""; }} />
      <div className="imp-drop" onClick={() => file.current?.click()} onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) read(f); }} role="button" tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && file.current?.click()}>
        <Icon name="cloud-upload" />
        <span><b>Choose a spreadsheet</b> or drop it here</span>
        <span className="xs faint">{name || "Excel (.xlsx), CSV or text - a column of symbols or company names"}</span>
      </div>
      <textarea className="inp mono imp-paste" rows={4} value={text} onChange={(e) => { setText(e.target.value); setName(""); }}
        placeholder={"…or paste: one per line or comma-separated\nTCS, INFY.NS, HDFCBANK\nHindustan Aeronautics"} />
      {text.trim() && (
        <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
          <span className={got.found.length ? "up xs" : "faint xs"}><Icon name="pass" className="xs" /> {got.found.length} recognised</span>
          {got.missed.length > 0 && <span className="warn xs" title={got.missed.join(", ")}><Icon name="warning" className="xs" /> {got.missed.length} not recognised: {got.missed.slice(0, 3).join(", ")}{got.missed.length > 3 ? "…" : ""}</span>}
          <span className="spacer" />
          <button className="btn xs" disabled={!got.found.length} onClick={() => { add(got.found); setText(""); setName(""); }}><Icon name="add" className="xs" />Add {got.found.length}</button>
        </div>
      )}
    </div>
  );
}

function FromList({ add, exceptList }: { add: (e: Entry[]) => void; exceptList?: string }) {
  const lib = useWatchlists();
  const lists = (lib.data?.lists ?? []).filter((l) => l.id !== exceptList && l.count > 0);
  if (!lists.length) return <span className="xs faint">There is no other list with companies yet.</span>;
  return (
    <div className="imp-lists">
      {lists.map((l) => (
        <button key={l.id} onClick={() => add(l.companies.map((c) => ({ ticker: c.ticker, name: c.name, sector: c.sector })))} style={{ ["--wc" as string]: l.color }}>
          <i className="wl-sw" /><span className="grow ellipsis">{l.name}</span><span className="xs faint">{l.count}</span><Icon name="add" className="xs" />
        </button>
      ))}
    </div>
  );
}
