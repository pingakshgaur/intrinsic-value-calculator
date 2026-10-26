import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCharts, useDownloads, useEnsemble, useExcluded, useHybridDetail, useMetrics, useValuation } from "../lib/hooks";
import { Metrics, Valuation } from "../lib/api";
import { computeMetrics } from "../lib/metrics";
import { useScope } from "../lib/scope";
import { ScopeNote } from "../components/ScopePicker";
import { ago, bytes, isNum, money, pct, pctUnits, shortName, slug, titleCase } from "../lib/format";
import { HM_COLOR, LENSES, LENS_COLOR, LENS_NAME, SERIES } from "../lib/labels";
import { Empty, Icon, PageHeader, Panel, QueryView, Tabs, Tip } from "../components/ui";
import { RunButton } from "../components/RunButton";
import { Leaderboard } from "./CommandCenter";

type Tab = "board" | "explore" | "hybrid" | "ensemble" | "charts" | "excluded" | "files";
const color = (m: string, models: string[]) => (m === "HYBRID MODEL" ? HM_COLOR : m === "Ensemble" ? "#C586C0" : SERIES[Math.max(0, models.indexOf(m)) % SERIES.length]);

export function Performance() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "board";
  const q = useValuation();
  const scope = useScope();
  const setTab = (t: Tab) => { const p = new URLSearchParams(params); p.set("tab", t); setParams(p, { replace: true }); };
  // a watchlist in focus: its companies' rows, and the metrics recomputed from them
  const scoped = useMemo<Valuation | undefined>(() => (q.data && scope.list ? { ...q.data, rows: q.data.rows.filter((r) => scope.has({ company: r.company })) } : q.data), [q.data, scope]);
  const allCos = q.data ? new Set(q.data.rows.map((r) => r.company)).size : 0;
  const cos = scoped ? new Set(scoped.rows.map((r) => r.company)).size : 0;
  return (
    <div className="page">
      <PageHeader crumbs={[{ label: "Models & data" }, { label: "Model Performance" }]} title="Model Performance"
        sub={q.data?.available ? `${cos} companies · ${q.data.models.length} models · report ${ago(q.data.updated)} · scored against the 1-May price` : "Every model, every financial year, scored against the market"}
        actions={<><Link to="/operations" className="btn sec"><Icon name="settings" className="sm" />Run options</Link><RunButton kind="valuation" label="Run valuation report" icon="graph" /></>} />
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "board", label: "Leaderboard", icon: "list-ordered" },
        { id: "explore", label: "Company explorer", icon: "graph-line" },
        { id: "hybrid", label: "HYBRID MODEL", icon: "beaker" },
        { id: "ensemble", label: "Ensemble", icon: "layers" },
        { id: "charts", label: "Chart gallery", icon: "file-media" },
        { id: "excluded", label: "Left out", icon: "exclude" },
        { id: "files", label: "Files", icon: "files" },
      ]} />
      {q.data?.available && <ScopeNote shown={cos} total={allCos} />}
      <QueryView q={q} rows={10}>
        {(all) => { const d = scoped ?? all; return scope.list && d.available && !d.rows.length && tab !== "charts" && tab !== "files"
          ? <Panel><Empty icon="library" title={`No company on “${scope.list.name}” is in the valuation report`} action={<button className="btn sec" onClick={() => scope.set(null)}>Show every company</button>}>Add them to Coverage on the Universe page, then run the valuation report.</Empty></Panel>
          : !d.available && ["explore", "hybrid", "ensemble"].includes(tab)
          ? <Panel><Empty icon="graph-line" title="No valuation report yet" action={<RunButton kind="valuation" label="Run valuation report" icon="graph" />}>The report values every company for every year with every model, including the HYBRID MODEL.</Empty></Panel>
          : <>
            {tab === "board" && <Board scoped={scope.list && d.available ? d : null} />}
            {tab === "explore" && <Explore d={d} />}
            {tab === "hybrid" && <HybridDetail d={d} />}
            {tab === "ensemble" && <EnsembleDetail d={d} />}
            {tab === "charts" && <Gallery />}
            {tab === "excluded" && <Excluded />}
            {tab === "files" && <Files />}
          </>; }}
      </QueryView>
    </div>
  );
}

function Board({ scoped }: { scoped: Valuation | null }) {
  const q = useMetrics();
  const local = useMemo(() => (scoped ? computeMetrics(scoped.rows, scoped.models) : null), [scoped]);
  return (
    <QueryView q={q}>
      {(server) => {
        // a watchlist in focus: the same tables, recomputed for its companies
        const m: Pick<Metrics, "overall" | "by_year" | "by_sector" | "win_rate" | "updated"> = local ? { ...local, updated: server.updated } : server;
        if (!m.overall.length) return <Panel><Empty icon="target" title="No accuracy metrics yet" action={<RunButton kind="valuation" label="Run valuation report" icon="graph" />}>A valuation run with charts switched on writes them.</Empty></Panel>;
        const models = m.overall.map((r) => String(r.Model));
        const years = [...new Set(m.by_year.map((r) => String(r["Financial Year"])))];
        const byYear = years.map((y) => ({ fy: y, ...Object.fromEntries(m.by_year.filter((r) => r["Financial Year"] === y).map((r) => [String(r.Model), r["MedAPE %"]])) }));
        const sectors = [...new Set(m.by_sector.map((r) => String(r["Sector Name"])))];
        const wins = m.win_rate.map((r) => ({ model: String(r.Model), win: r["Win rate %"] }));
        return (
          <>
            <Leaderboard rows={m.overall} updated={m.updated} />
            <div className="grid c-21">
              <Panel title="Median error by financial year">
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={byYear} margin={{ top: 6, right: 14, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="2 4" /><XAxis dataKey="fy" tickLine={false} axisLine={{ stroke: "var(--line)" }} /><YAxis unit="%" tickLine={false} axisLine={false} width={44} />
                    <Tooltip content={<Tip fmt={(x) => pctUnits(x)} title={(l) => `FY ${l}`} />} /><Legend iconType="plainline" />
                    {models.map((mm) => <Line key={mm} dataKey={mm} stroke={color(mm, models)} strokeWidth={mm === "HYBRID MODEL" ? 3 : 1.3} strokeOpacity={mm === "HYBRID MODEL" ? 1 : 0.75} dot={false} connectNulls />)}
                  </LineChart>
                </ResponsiveContainer>
              </Panel>
              <Panel title="Win rate" meta="closest to the price">
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={wins} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
                    <XAxis type="number" unit="%" tickLine={false} axisLine={{ stroke: "var(--line)" }} /><YAxis type="category" dataKey="model" width={130} tickLine={false} axisLine={false} tick={{ fill: "var(--fg)", fontSize: 11 }} />
                    <Tooltip content={<Tip fmt={(x) => pctUnits(x)} />} cursor={{ fill: "var(--hover)" }} />
                    <Bar dataKey="win" name="Win rate" fill="#57A3F8" radius={[0, 3, 3, 0]} barSize={11} />
                  </BarChart>
                </ResponsiveContainer>
              </Panel>
            </div>
            <Panel title="Sector × model error matrix" meta="median absolute % error · darker = worse" flush>
              <div className="dg-wrap">
                <table className="dg dense">
                  <thead><tr><th className="sticky">Sector</th>{models.map((mm) => <th key={mm} className="r" style={mm === "HYBRID MODEL" ? { color: HM_COLOR } : undefined}>{mm}</th>)}</tr></thead>
                  <tbody>
                    {sectors.map((s) => (
                      <tr key={s}>
                        <td className="sticky strong">{s}</td>
                        {models.map((mm) => {
                          const v = m.by_sector.find((x) => x["Sector Name"] === s && x.Model === mm)?.["MedAPE %"];
                          return <td key={mm} className="r"><span className="heat" style={{ background: `rgba(239,135,115,${isNum(v) ? Math.min(0.55, v / 150) : 0})` }}>{pctUnits(v, 0)}</span></td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </>
        );
      }}
    </QueryView>
  );
}

function useCompany(d: Valuation) {
  const [params, setParams] = useSearchParams();
  const companies = useMemo(() => [...new Set(d.rows.map((r) => r.company))].sort(), [d.rows]);
  const cur = params.get("company");
  const company = cur && companies.includes(cur) ? cur : companies[0] ?? "";
  const set = (c: string) => { const p = new URLSearchParams(params); p.set("company", c); setParams(p, { replace: true }); };
  return { company, companies, set };
}

function Picker({ c }: { c: ReturnType<typeof useCompany> }) {
  return (
    <select className="sel" value={c.company} onChange={(e) => c.set(e.target.value)} style={{ minWidth: 280 }}>
      {c.companies.map((x) => <option key={x} value={x}>{shortName(x)}</option>)}
    </select>
  );
}

function Explore({ d }: { d: Valuation }) {
  const c = useCompany(d);
  const [hidden, setHidden] = useState<Set<string>>(new Set(["XGBoost", "Random Forest", "LightGBM", "MLP Neural Network"]));
  const [log, setLog] = useState(false);
  const rows = d.rows.filter((r) => r.company === c.company);
  const models = d.models.filter((m) => rows.some((r) => isNum(r.values[m])));
  const data = rows.map((r) => ({ fy: r.fy, price: r.price, ...Object.fromEntries(models.map((m) => [m, r.values[m]])) }));
  return (
    <>
      <Panel title={<span className="row" style={{ gap: 10 }}><Picker c={c} /><span className="muted small">{rows[0]?.sector}</span></span>}
        tools={<><Link to={`/studio?company=${slug(c.company)}`} className="btn xs ghost"><Icon name="beaker" className="xs" />Studio</Link><div className="seg"><button className={!log ? "on" : ""} onClick={() => setLog(false)}>Linear</button><button className={log ? "on" : ""} onClick={() => setLog(true)}>Log</button></div></>}>
        <div className="row wrap" style={{ gap: 6, marginBottom: 10 }}>
          {models.map((m) => { const on = !hidden.has(m); return <button key={m} className={`chip ${on ? "on" : ""}`} onClick={() => { const s = new Set(hidden); if (on) s.add(m); else s.delete(m); setHidden(s); }}><span className="sw" style={{ background: color(m, d.models) }} />{m}</button>; })}
        </div>
        <ResponsiveContainer width="100%" height={340}>
          <LineChart data={data} margin={{ top: 6, right: 16, bottom: 0, left: 4 }}>
            <CartesianGrid strokeDasharray="2 4" /><XAxis dataKey="fy" tickLine={false} axisLine={{ stroke: "var(--line)" }} />
            <YAxis scale={log ? "log" : "auto"} domain={log ? ["auto", "auto"] : [0, "auto"]} allowDataOverflow tickLine={false} axisLine={false} width={72} tickFormatter={(x) => money(x, 0)} />
            <Tooltip content={<Tip fmt={(x) => money(x)} title={(l) => `FY ${l}`} />} />
            <Line type="monotone" dataKey="price" name="1-May price" stroke="#E0B97F" strokeWidth={3} dot={{ r: 3 }} connectNulls />
            {models.filter((m) => !hidden.has(m)).map((m) => <Line key={m} type="monotone" dataKey={m} name={m} stroke={color(m, d.models)} strokeWidth={m === "HYBRID MODEL" ? 3 : 1.5} dot={{ r: 2 }} connectNulls />)}
          </LineChart>
        </ResponsiveContainer>
      </Panel>
      <Panel title="Value ÷ price by year" meta="green above the price, red below" flush>
        <div className="dg-wrap">
          <table className="dg dense">
            <thead><tr><th className="sticky">FY</th><th className="r">Price</th>{models.map((m) => <th key={m} className="r" style={m === "HYBRID MODEL" ? { color: HM_COLOR } : undefined}>{m}</th>)}</tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.fy}>
                  <td className="sticky mono">{r.fy}</td><td className="r mono strong">{money(r.price)}</td>
                  {models.map((m) => {
                    const v = r.values[m];
                    if (!isNum(v)) return <td key={m} className="r faint">—</td>;
                    const g = isNum(r.price) && r.price > 0 ? v / r.price - 1 : 0;
                    const a = Math.min(0.5, Math.abs(g) / 2);
                    return <td key={m} className="r"><span className="heat" style={{ background: g >= 0 ? `rgba(134,207,134,${a})` : `rgba(239,135,115,${a})` }} title={pct(g, 0, true)}>{money(v)}</span></td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

function HybridDetail({ d }: { d: Valuation }) {
  const c = useCompany(d);
  const q = useHybridDetail();
  return (
    <QueryView q={q}>
      {(h) => {
        const rows = h.rows.filter((r) => r["Company name"] === c.company);
        const data = rows.map((r) => ({ fy: r["Financial Year"], price: r["Market Price"], value: r["HYBRID MODEL Value"], band: isNum(r["Low (P10)"]) && isNum(r["High (P90)"]) ? [r["Low (P10)"], r["High (P90)"]] : null }));
        const weights = rows.map((r) => ({ fy: r["Financial Year"], ...Object.fromEntries(LENSES.map((l) => [LENS_NAME[l], isNum(r[`${l} weight`]) ? r[`${l} weight`] : 0])) }));
        const last = rows[rows.length - 1];
        return (
          <>
            <Panel title={<span className="row" style={{ gap: 10 }}><Picker c={c} /><span className="tag hm">HYBRID MODEL</span>{last && <span className="muted small">{titleCase(String(last.Regime ?? ""))}</span>}</span>} meta="point-in-time: each year sees only its own and earlier accounts">
              {!rows.length ? <Empty icon="beaker" title="No HYBRID MODEL detail" /> : (
                <ResponsiveContainer width="100%" height={320}>
                  <ComposedChart data={data} margin={{ top: 6, right: 16, bottom: 0, left: 4 }}>
                    <CartesianGrid strokeDasharray="2 4" /><XAxis dataKey="fy" tickLine={false} axisLine={{ stroke: "var(--line)" }} /><YAxis tickLine={false} axisLine={false} width={72} tickFormatter={(x) => money(x, 0)} />
                    <Tooltip content={<Tip fmt={(x) => (Array.isArray(x) ? `${money(x[0], 0)} – ${money(x[1], 0)}` : money(x))} title={(l) => `FY ${l}`} />} /><Legend iconType="plainline" />
                    <Area type="monotone" dataKey="band" name="P10–P90" stroke="none" fill={HM_COLOR} fillOpacity={0.18} connectNulls />
                    <Line type="monotone" dataKey="value" name="HYBRID MODEL" stroke={HM_COLOR} strokeWidth={3} dot={{ r: 3 }} connectNulls />
                    <Line type="monotone" dataKey="price" name="1-May price" stroke="#E0B97F" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                  </ComposedChart>
                </ResponsiveContainer>
              )}
            </Panel>
            {rows.length > 0 && (
              <div className="grid c2">
                <Panel title="Lens weights by year" meta="type weights × calibrated skill">
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={weights} margin={{ top: 4, right: 10, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeDasharray="2 4" vertical={false} /><XAxis dataKey="fy" tickLine={false} axisLine={{ stroke: "var(--line)" }} /><YAxis tickFormatter={(x) => pct(x, 0)} tickLine={false} axisLine={false} width={40} domain={[0, 1]} />
                      <Tooltip content={<Tip fmt={(x) => pct(x, 0)} />} cursor={{ fill: "var(--hover)" }} /><Legend />
                      {LENSES.map((l) => <Bar key={l} dataKey={LENS_NAME[l]} stackId="w" fill={LENS_COLOR[l]} fillOpacity={0.9} />)}
                    </BarChart>
                  </ResponsiveContainer>
                </Panel>
                <Panel title={`Lenses · ${last["Financial Year"]}`} flush>
                  <table className="dg dense">
                    <thead><tr><th>Lens</th><th className="r">Value</th><th className="r">Weight</th><th className="r">Calibration</th></tr></thead>
                    <tbody>{LENSES.map((l) => (
                      <tr key={l}><td><span className="row" style={{ gap: 8 }}><i style={{ width: 8, height: 8, borderRadius: 2, background: LENS_COLOR[l], display: "inline-block" }} />{LENS_NAME[l]}</span></td>
                        <td className="r mono">{money(last[`${l} value`] as number | null)}</td><td className="r mono">{pct(last[`${l} weight`] as number | null, 0)}</td>
                        <td className="r mono faint">{isNum(last[`${l} calibration`]) ? `×${(last[`${l} calibration`] as number).toFixed(2)}` : "—"}</td></tr>
                    ))}</tbody>
                  </table>
                </Panel>
              </div>
            )}
          </>
        );
      }}
    </QueryView>
  );
}

function EnsembleDetail({ d }: { d: Valuation }) {
  const c = useCompany(d);
  const q = useEnsemble();
  return (
    <QueryView q={q}>
      {(h) => {
        const rows = h.rows.filter((r) => r["Company name"] === c.company);
        const key = rows[0] && rows[0]["Ensemble Value"] !== undefined ? "Ensemble Value" : "Hybrid Value";
        const data = rows.map((r) => ({ fy: r["Financial Year"], price: r["Market Price"], v: r[key], band: isNum(r["Low (P10)"]) && isNum(r["High (P90)"]) ? [r["Low (P10)"], r["High (P90)"]] : null }));
        return (
          <Panel title={<span className="row" style={{ gap: 10 }}><Picker c={c} /><span className="tag">Ensemble — formerly “Hybrid”</span></span>}>
            {!rows.length ? <Empty icon="layers" title="No Ensemble detail" /> : (
              <ResponsiveContainer width="100%" height={320}>
                <ComposedChart data={data} margin={{ top: 6, right: 16, bottom: 0, left: 4 }}>
                  <CartesianGrid strokeDasharray="2 4" /><XAxis dataKey="fy" tickLine={false} axisLine={{ stroke: "var(--line)" }} /><YAxis tickLine={false} axisLine={false} width={72} tickFormatter={(x) => money(x, 0)} />
                  <Tooltip content={<Tip fmt={(x) => (Array.isArray(x) ? `${money(x[0], 0)} – ${money(x[1], 0)}` : money(x))} />} /><Legend iconType="plainline" />
                  <Area type="monotone" dataKey="band" name="P10–P90" stroke="none" fill="#C586C0" fillOpacity={0.16} connectNulls />
                  <Line type="monotone" dataKey="v" name="Ensemble" stroke="#C586C0" strokeWidth={2.5} dot={{ r: 3 }} connectNulls />
                  <Line type="monotone" dataKey="price" name="1-May price" stroke="#E0B97F" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </Panel>
        );
      }}
    </QueryView>
  );
}

function Gallery() {
  const q = useCharts();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <QueryView q={q}>
      {(names) => !names.length ? <Panel><Empty icon="file-media" title="No charts yet">The analysis stage of a valuation run draws them.</Empty></Panel> : (
        <>
          <div className="gallery">{names.map((n) => <figure key={n} onClick={() => setOpen(n)}><img src={`/api/charts/${n}`} alt={n} loading="lazy" /><figcaption>{titleCase(n.replace(/\.png$/, ""))}</figcaption></figure>)}</div>
          {open && <div className="lightbox" onClick={() => setOpen(null)}><img src={`/api/charts/${open}`} alt={open} /></div>}
        </>
      )}
    </QueryView>
  );
}

function Excluded() {
  const q = useExcluded();
  const scope = useScope();
  return (
    <QueryView q={q}>
      {(all) => { const d = { ...all, rows: all.rows.filter((r) => scope.has({ company: String(r["Company name"] ?? "") })) }; return !d.rows.length ? <Panel><Empty icon="pass" title="Every company was used">Nobody was left out of the last report for missing data.</Empty></Panel> : (
        <Panel flush>
          <table className="dg">
            <thead><tr><th>Company</th><th>Problem</th><th>What went wrong</th><th>What you can do</th></tr></thead>
            <tbody>{d.rows.map((r, i) => <tr key={i}><td className="strong">{r["Company name"]}</td><td><span className="tag warn">{r["Type of problem"]}</span></td><td style={{ whiteSpace: "normal" }} className="small">{r["In plain words, what went wrong"]}</td><td style={{ whiteSpace: "normal" }} className="small muted">{r["What you can do about it"]}</td></tr>)}</tbody>
          </table>
        </Panel>
      ); }}
    </QueryView>
  );
}

function Files() {
  const q = useDownloads();
  return (
    <QueryView q={q}>
      {(files) => !files.length ? <Panel><Empty icon="files" title="No files yet" /></Panel> : (
        <Panel flush>
          <table className="dg">
            <thead><tr><th>File</th><th>Updated</th><th className="r">Size</th><th /></tr></thead>
            <tbody>{files.map((f) => (
              <tr key={f.key}><td><span className="row"><Icon name={f.file.endsWith(".xlsx") ? "table" : f.file.endsWith(".html") ? "globe" : "file"} className="sm faint" /><span className="mono">{f.file}</span></span></td>
                <td className="muted">{ago(f.updated)}</td><td className="r mono faint">{bytes(f.size)}</td>
                <td className="r"><a className="btn xs sec" href={`/api/downloads/${f.key}`} download><Icon name="desktop-download" className="xs" />Download</a></td></tr>
            ))}</tbody>
          </table>
        </Panel>
      )}
    </QueryView>
  );
}
