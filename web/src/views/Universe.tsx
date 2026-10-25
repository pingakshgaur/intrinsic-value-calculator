import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useBlocker } from "react-router-dom";
import { api, Company } from "../lib/api";
import { useCompanies } from "../lib/hooks";
import { ErrorNote, Icon, PageHeader, QueryView } from "../components/ui";
import { useApp } from "../components/workbenchContext";

const CAPS = ["Large", "Mid", "Small", ""];
const TICKER = /^[A-Za-z0-9&\-_.]{0,30}$/;
interface Row extends Company { _k: number }
let seq = 0;
const keyed = (rs: Company[]): Row[] => rs.map((r) => ({ ...r, _k: ++seq }));
const plain = (rs: Row[]) => rs.filter((r) => r.name.trim()).map(({ _k, ...r }) => ({ ...r, name: r.name.trim(), sector: r.sector.trim(), ticker: r.ticker.trim().toUpperCase() }));

function parseCsv(text: string): Company[] {
  const rows: string[][] = [];
  let cur: string[] = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) { if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (ch === '"') q = false; else cell += ch; }
    else if (ch === '"') q = true;
    else if (ch === "," || ch === ";" || ch === "\t") { cur.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; cur.push(cell); rows.push(cur); cur = []; cell = ""; }
    else cell += ch;
  }
  if (cell || cur.length) { cur.push(cell); rows.push(cur); }
  const clean = rows.filter((r) => r.some((c) => c.trim()));
  const start = clean[0] && /company|name/i.test(clean[0][0]) ? 1 : 0;
  return clean.slice(start).map((r) => ({ name: (r[0] ?? "").trim(), sector: (r[1] ?? "").trim(), cap: (r[2] ?? "").trim(), ticker: (r[3] ?? "").trim() }));
}

export function Universe() {
  const q = useCompanies();
  return <div className="page fill"><QueryView q={q} rows={12}>{(rows) => <Editor initial={rows} />}</QueryView></div>;
}

function Editor({ initial }: { initial: Company[] }) {
  const [rows, setRows] = useState<Row[]>(() => keyed(initial));
  const [base, setBase] = useState(() => JSON.stringify(initial));
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState("");
  const [sector, setSector] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const app = useApp();
  const dirty = JSON.stringify(rows.map(({ _k, ...r }) => r)) !== base;
  const blocker = useBlocker(dirty);
  useEffect(() => { const h = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); }; window.addEventListener("beforeunload", h); return () => window.removeEventListener("beforeunload", h); }, [dirty]);

  const sectors = useMemo(() => [...new Set(rows.map((r) => r.sector).filter(Boolean))].sort(), [rows]);
  const problems = useMemo(() => {
    const p: Record<number, string> = {};
    const seen = new Set<string>();
    for (const r of rows) {
      const n = r.name.trim().toLowerCase();
      if (!n) p[r._k] = "name is empty";
      else if (seen.has(n)) p[r._k] = "duplicate name";
      else if (!TICKER.test(r.ticker.trim())) p[r._k] = "ticker has unexpected characters";
      else if (!r.sector.trim()) p[r._k] = "no sector — peer comparisons need one";
      seen.add(n);
    }
    return p;
  }, [rows]);
  const blocking = Object.values(problems).filter((x) => x === "duplicate name" || x.startsWith("ticker")).length;
  const update = (k: number, patch: Partial<Company>) => setRows((rs) => rs.map((r) => (r._k === k ? { ...r, ...patch } : r)));
  const f = filter.trim().toLowerCase();
  const shown = rows.filter((r) => (!f || `${r.name} ${r.sector} ${r.ticker}`.toLowerCase().includes(f)) && (!sector || r.sector === sector));
  const allOn = shown.length > 0 && shown.every((r) => checked.has(r._k));

  const saveAll = async () => {
    setSaving(true); setErr(null);
    try {
      const body = plain(rows);
      await api.put("/api/companies", body);
      setBase(JSON.stringify(body)); setRows(keyed(body)); setChecked(new Set());
      qc.invalidateQueries({ queryKey: ["companies"] }); qc.invalidateQueries({ queryKey: ["status"] });
      app.toast(`Universe saved — ${body.length} companies`, "ok");
    } catch (e) { setErr(e); } finally { setSaving(false); }
  };
  const exportCsv = () => {
    const lines = [["company name", "sector name", "market cap", "ticker"], ...plain(rows).map((r) => [r.name, r.sector, r.cap, r.ticker])].map((r) => r.map((c) => `"${c.replace(/"/g, '""')}"`).join(","));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    a.download = "companies.csv"; a.click(); URL.revokeObjectURL(a.href);
  };
  const importCsv = async (fl: File) => {
    try {
      const parsed = parseCsv(await fl.text()).filter((r) => r.name);
      if (!parsed.length) throw new Error("No rows found. Expected columns: company name, sector name, market cap, ticker.");
      const existing = new Set(rows.map((r) => r.name.trim().toLowerCase()));
      const fresh = parsed.filter((r) => !existing.has(r.name.toLowerCase()));
      setRows((rs) => [...keyed(fresh), ...rs]);
      app.toast(`Imported ${fresh.length} new compan${fresh.length === 1 ? "y" : "ies"} (${parsed.length - fresh.length} already listed) — review and save`, "info");
    } catch (e) { setErr(e); }
  };

  return (
    <>
      <PageHeader crumbs={[{ label: "Models & data" }, { label: "Universe" }]} title="Universe"
        sub={`${rows.length} companies across ${sectors.length} sectors — every valuation and research job works through this list`}
        actions={<>
          <input ref={file} type="file" accept=".csv,text/csv" hidden onChange={(e) => { const fl = e.target.files?.[0]; if (fl) importCsv(fl); e.target.value = ""; }} />
          <button className="btn sec" onClick={() => file.current?.click()}><Icon name="cloud-upload" className="sm" />Import CSV</button>
          <button className="btn sec" onClick={exportCsv}><Icon name="desktop-download" className="sm" />Export</button>
          <button className="btn" disabled={!dirty || saving || blocking > 0} onClick={saveAll} title={blocking ? "Fix duplicate names and bad tickers first" : undefined}><Icon name={saving ? "loading" : "save"} className={`sm ${saving ? "spin" : ""}`} />Save{dirty ? " changes" : ""}</button>
        </>} />
      {blocker.state === "blocked" && <div className="note wrn"><Icon name="warning" /><div className="grow">Unsaved changes to the universe.</div><button className="btn xs sec" onClick={() => blocker.reset?.()}>Stay</button><button className="btn xs danger" onClick={() => blocker.proceed?.()}>Discard and leave</button></div>}
      {err != null && <ErrorNote error={err} />}
      <section className="panel" style={{ flex: 1, minHeight: 0 }}>
        <div className="toolbar">
          <div className="search" style={{ width: 260 }}><Icon name="search" /><input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by name, sector or ticker" /></div>
          <select className="sel" value={sector} onChange={(e) => setSector(e.target.value)}><option value="">All sectors</option>{sectors.map((s) => <option key={s}>{s}</option>)}</select>
          <button className="btn sec sm" onClick={() => { setFilter(""); setSector(""); setRows((rs) => [{ name: "", sector: "", cap: "Large", ticker: "", _k: ++seq }, ...rs]); }}><Icon name="add" className="sm" />Add row</button>
          {checked.size > 0 && (
            <>
              <span className="tag">{checked.size} selected</span>
              <select className="sel sm" value="" onChange={(e) => { const s = e.target.value; if (s) setRows((rs) => rs.map((r) => (checked.has(r._k) ? { ...r, sector: s } : r))); }}>
                <option value="">Set sector…</option>{sectors.map((s) => <option key={s}>{s}</option>)}
              </select>
              <button className="btn danger sm" onClick={() => { setRows((rs) => rs.filter((r) => !checked.has(r._k))); setChecked(new Set()); }}><Icon name="trash" className="sm" />Delete</button>
            </>
          )}
          <span className="spacer" />
          {dirty && <span className="tag info">unsaved</span>}
          <span className="faint xs">Ticker: NSE symbol + .NS (BSE .BO); blank = look up by name</span>
        </div>
        <datalist id="sectors">{sectors.map((s) => <option key={s} value={s} />)}</datalist>
        <div className="dg-wrap">
          <table className="dg dense">
            <thead><tr>
              <th style={{ width: 36 }}><input type="checkbox" className="cb" checked={allOn} onChange={() => setChecked(allOn ? new Set() : new Set(shown.map((r) => r._k)))} /></th>
              <th style={{ width: 28 }} /><th>Company name</th><th>Sector</th><th style={{ width: 120 }}>Size</th><th style={{ width: 170 }}>Ticker</th>
            </tr></thead>
            <tbody>
              {shown.map((r) => {
                const pb = problems[r._k];
                const hard = pb === "duplicate name" || pb?.startsWith("ticker");
                return (
                  <tr key={r._k} className={checked.has(r._k) ? "sel" : ""}>
                    <td><input type="checkbox" className="cb" checked={checked.has(r._k)} onChange={() => { const s = new Set(checked); if (s.has(r._k)) s.delete(r._k); else s.add(r._k); setChecked(s); }} /></td>
                    <td title={pb}>{pb && <Icon name="warning" className={`sm ${hard ? "down" : "warn"}`} />}</td>
                    <td className="edit"><input className={`inp ${pb === "duplicate name" ? "bad" : ""}`} value={r.name} placeholder="Company name" onChange={(e) => update(r._k, { name: e.target.value })} /></td>
                    <td className="edit"><input className="inp" list="sectors" value={r.sector} placeholder="Sector" onChange={(e) => update(r._k, { sector: e.target.value })} /></td>
                    <td className="edit"><select className="sel" value={r.cap} onChange={(e) => update(r._k, { cap: e.target.value })}>{CAPS.map((c) => <option key={c} value={c}>{c || "—"}</option>)}</select></td>
                    <td className="edit"><input className={`inp mono ${pb?.startsWith("ticker") ? "bad" : ""}`} value={r.ticker} placeholder="TCS.NS" onChange={(e) => update(r._k, { ticker: e.target.value })} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!shown.length && <div className="muted" style={{ padding: 28, textAlign: "center" }}>No rows match.</div>}
        </div>
      </section>
    </>
  );
}
