import { Fragment, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCharts, useDownloads, useEnsemble, useExcluded, useHybridDetail, useMetrics, useValuation } from "../lib/hooks";
import { Metrics, Valuation } from "../lib/api";
import { computeMetrics } from "../lib/metrics";
import { bestBySector, NEAR_BAND, SectorForecast, sectorForecasts, winsBySector } from "../lib/sectors";
import { useScope } from "../lib/scope";
import { ScopeNote } from "../components/ScopePicker";
import { ago, bytes, isNum, money, pct, pctUnits, shortName, slug, titleCase } from "../lib/format";
import { HM_COLOR, LENSES, LENS_COLOR, LENS_NAME, SERIES } from "../lib/labels";
import { Empty, Icon, PageHeader, Panel, QueryView, Tabs, Tip } from "../components/ui";
import { RunButton } from "../components/RunButton";
import { TrainingData } from "../components/TrainingData";
import { Leaderboard } from "./CommandCenter";
import { Select } from "../components/Select";
import { ImageViewer } from "../components/ImageViewer";
import { companyPath } from "../lib/company";

type Tab = "board" | "sectors" | "company" | "training" | "files";
// addresses of the tabs this page used to have
const OLD_TAB: Record<string, Tab> = { explore: "company", hybrid: "company", ensemble: "company", charts: "files", excluded: "files", learning: "training" };
const color = (m: string, models: string[]) => (m === "HYBRID MODEL" ? HM_COLOR : m === "Ensemble" ? "#C586C0" : SERIES[Math.max(0, models.indexOf(m)) % SERIES.length]);

export function Performance() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab") ?? "board";
  const tab = (OLD_TAB[raw] ?? raw) as Tab;
  const q = useValuation();
  const scope = useScope();
  const setTab = (t: Tab) => { const p = new URLSearchParams(params); p.set("tab", t); p.delete("view"); setParams(p, { replace: true }); };
  // a watchlist in focus: its companies' rows, and the metrics recomputed from them
  const scoped = useMemo<Valuation | undefined>(() => (q.data && scope.list ? { ...q.data, rows: q.data.rows.filter((r) => scope.has({ company: r.company })) } : q.data), [q.data, scope]);
  const allCos = q.data ? new Set(q.data.rows.map((r) => r.company)).size : 0;
  const cos = scoped ? new Set(scoped.rows.map((r) => r.company)).size : 0;
  const needsReport = tab === "sectors" || tab === "company";
  return (
    <div className="page">
      <PageHeader crumbs={[{ label: "Operations" }, { label: "Model Performance" }]} title="Model Performance"
        sub={q.data?.available ? `${cos} companies · ${q.data.models.length} models · report ${ago(q.data.updated)} · scored against the 1-May price` : "Every model, every financial year, scored against the market"}
        actions={<RunButton kind="valuation" label="Run valuation report" icon="graph" />} />
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "board", label: "Leaderboard", icon: "list-ordered" },
        { id: "sectors", label: "Sectors", icon: "symbol-class" },
        { id: "company", label: "Company", icon: "graph-line" },
        { id: "training", label: "Learning pool", icon: "mortar-board" },
        { id: "files", label: "Files & charts", icon: "files" },
      ]} />
      {q.data?.available && tab !== "training" && tab !== "files" && <ScopeNote shown={cos} total={allCos} />}
      {tab === "training" ? <TrainingData /> : tab === "files" ? <FilesTab /> : (
        <QueryView q={q} rows={10}>
          {(all) => { const d = scoped ?? all; return scope.list && d.available && !d.rows.length
            ? <Panel><Empty icon="library" title={`No company on “${scope.list.name}” is in the valuation report`} action={<button className="btn sec" onClick={() => scope.set(null)}>Show every company</button>}>Run the valuation report on this watchlist from Operations to value its companies.</Empty></Panel>
            : !d.available && needsReport
            ? <Panel><Empty icon="graph-line" title="No valuation report yet" action={<RunButton kind="valuation" label="Run valuation report" icon="graph" />}>The report values every company for every year with every model, including the HYBRID MODEL.</Empty></Panel>
            : <>
              {tab === "board" && <Board scoped={scope.list && d.available ? d : null} />}
              {tab === "sectors" && <Sectors d={d} scoped={!!scope.list} />}
              {tab === "company" && <CompanyTab d={d} />}
            </>; }}
        </QueryView>
      )}
    </div>
  );
}

type Board4 = Pick<Metrics, "overall" | "by_year" | "by_sector" | "win_rate" | "updated">;
/** The server's metric tables, or the same tables recomputed for a watchlist in focus. */
function useBoardMetrics(scoped: Valuation | null) {
  const q = useMetrics();
  const local = useMemo(() => (scoped ? computeMetrics(scoped.rows, scoped.models) : null), [scoped]);
  const m: Board4 | undefined = q.data ? (local ? { ...local, updated: q.data.updated } : q.data) : undefined;
  return { q, m };
}

function Board({ scoped }: { scoped: Valuation | null }) {
  const { q, m } = useBoardMetrics(scoped);
  return (
    <QueryView q={q}>
      {() => {
        if (!m || !m.overall.length) return <Panel><Empty icon="target" title="No accuracy metrics yet" action={<RunButton kind="valuation" label="Run valuation report" icon="graph" />}>A valuation run with charts switched on writes them.</Empty></Panel>;
        const models = m.overall.map((r) => String(r.Model));
        const years = [...new Set(m.by_year.map((r) => String(r["Financial Year"])))];
        const byYear = years.map((y) => ({ fy: y, ...Object.fromEntries(m.by_year.filter((r) => r["Financial Year"] === y).map((r) => [String(r.Model), r["MedAPE %"]])) }));
        const wins = m.win_rate.map((r) => ({ model: String(r.Model), win: r["Win rate %"] }));
        return (
          <>
            <Leaderboard rows={m.overall} updated={m.updated} detail={(model) => <ModelDetail model={model} m={m} />} />
            <div className="grid c-21">
              <Panel title="Median error by financial year" meta="lower is better">
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
          </>
        );
      }}
    </QueryView>
  );
}

/** One model, opened from the leaderboard: its error year by year, and the sectors it values best and worst. */
function ModelDetail({ model, m }: { model: string; m: Board4 }) {
  const years = m.by_year.filter((r) => String(r.Model) === model && isNum(r["MedAPE %"])).map((r) => ({ fy: String(r["Financial Year"]), err: r["MedAPE %"] as number }));
  const best = bestBySector(m.by_sector);
  const mine = best.map((b) => { const i = b.ranked.findIndex((x) => x.model === model); return i < 0 ? null : { sector: b.sector, err: b.ranked[i].err, rank: i + 1, of: b.ranked.length }; })
    .filter(Boolean).sort((a, b) => a!.err - b!.err) as { sector: string; err: number; rank: number; of: number }[];
  const won = mine.filter((x) => x.rank === 1).length;
  const wr = m.win_rate.find((r) => String(r.Model) === model);
  const list = (xs: typeof mine) => xs.map((x) => <li key={x.sector}><span className="ellipsis">{x.sector}</span><span className="mono">{pctUnits(x.err, 0)}</span><span className="faint xs">#{x.rank} of {x.of}</span></li>);
  return (
    <div className="md">
      <div className="md-figs">
        <div><div className="k">Sectors won</div><div className="v">{won} <span className="faint xs">of {mine.length}</span></div></div>
        <div><div className="k">Closest to the price</div><div className="v">{wr ? pctUnits(wr["Win rate %"], 0) : "—"}</div><div className="s">of company-years</div></div>
        <div><div className="k">Latest year</div><div className="v">{years.length ? pctUnits(years[years.length - 1].err, 1) : "—"}</div><div className="s">{years.length ? `FY ${years[years.length - 1].fy}` : ""}</div></div>
      </div>
      {years.length > 1 && (
        <ResponsiveContainer width="100%" height={120}>
          <LineChart data={years} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="2 4" /><XAxis dataKey="fy" tickLine={false} axisLine={{ stroke: "var(--line)" }} minTickGap={20} /><YAxis unit="%" tickLine={false} axisLine={false} width={44} />
            <Tooltip content={<Tip fmt={(x) => pctUnits(x)} title={(l) => `FY ${l}`} />} />
            <Line dataKey="err" name="Median error" stroke={model === "HYBRID MODEL" ? HM_COLOR : "#57A3F8"} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
      {mine.length > 0 && (
        <div className="md-lists">
          <div><div className="label">Most accurate in</div><ul>{list(mine.slice(0, 4))}</ul></div>
          <div><div className="label">Least accurate in</div><ul>{list(mine.slice(-4).reverse())}</ul></div>
        </div>
      )}
    </div>
  );
}

// ================================================================ sectors
type SectorLens = "upside" | "move";
const upColor = (x: number | null | undefined) => (!isNum(x) ? "transparent" : x >= 0 ? `rgba(134,207,134,${Math.min(0.5, Math.abs(x) / 1.2)})` : `rgba(239,135,115,${Math.min(0.5, Math.abs(x) / 1.2)})`);

function Sectors({ d, scoped }: { d: Valuation; scoped: boolean }) {
  const { q, m } = useBoardMetrics(scoped ? d : null);
  const best = useMemo(() => bestBySector(m?.by_sector ?? []), [m]);
  const wins = useMemo(() => winsBySector(best), [best]);
  const fc = useMemo(() => sectorForecasts(d.rows, d.models), [d.rows, d.models]);
  // metric files name models without " Valuation"; the report's rows use the full name
  const full = (short: string) => d.models.find((x) => x.replace(/ Valuation$/, "") === short) ?? short;
  if (q.isLoading) return <QueryView q={q}>{() => null}</QueryView>;
  if (!best.length && !fc.length) return <Panel><Empty icon="symbol-class" title="No sector results yet" action={<RunButton kind="valuation" label="Run valuation report" icon="graph" />}>The valuation report scores every model in every sector.</Empty></Panel>;
  const hardest = [...best].sort((a, b) => b.bestErr - a.bestErr)[0];
  const easiest = [...best].sort((a, b) => a.bestErr - b.bestErr)[0];
  const cheapest = fc.find((s) => isNum(s.consensusUpside));
  return (
    <>
      <div className="band">
        <div><div className="k">Sectors</div><div className="v">{fc.length || best.length}</div><div className="s">{new Set(d.rows.map((r) => r.company)).size} companies</div></div>
        <div><div className="k">Best in most sectors</div><div className="v" style={{ fontSize: 17 }}>{wins[0]?.model ?? "—"}</div><div className="s">{wins[0] ? `most accurate in ${wins[0].sectors} of ${best.length}` : "run the report"}</div></div>
        <div><div className="k">Easiest to value</div><div className="v" style={{ fontSize: 17 }}>{easiest?.sector ?? "—"}</div><div className="s">{easiest ? `${easiest.best} within ${pctUnits(easiest.bestErr, 1)}` : ""}</div></div>
        <div><div className="k">Hardest to value</div><div className="v" style={{ fontSize: 17 }}>{hardest?.sector ?? "—"}</div><div className="s">{hardest ? `even the best model is ${pctUnits(hardest.bestErr, 1)} off` : ""}</div></div>
        <div><div className="k">Most below value</div><div className="v up" style={{ fontSize: 17 }}>{cheapest?.sector ?? "—"}</div><div className="s">{cheapest ? `models put it ${pct(cheapest.consensusUpside, 0, true)} above the price` : ""}</div></div>
      </div>
      {best.length > 0 && <BestModel best={best} wins={wins} colorOf={(mm) => color(full(mm), d.models)} />}
      {best.length > 0 && <ErrorMatrix best={best} />}
      {fc.length > 0 && <SectorForecastTable fc={fc} models={d.models} />}
      {fc.length > 0 && <Segregation fc={fc} />}
    </>
  );
}

function BestModel({ best, wins, colorOf }: { best: ReturnType<typeof bestBySector>; wins: ReturnType<typeof winsBySector>; colorOf: (m: string) => string }) {
  return (
    <div className="grid c-21">
      <Panel title="Which model suits each sector" meta="median error against the 1-May price · lower is better" flush>
        <div className="dg-wrap">
          <table className="dg dense">
            <thead><tr><th className="sticky">Sector</th><th>Best model</th><th className="r">Its error</th><th className="r">Within ±20%</th><th>Runner-up</th><th className="r">HYBRID MODEL</th><th className="r">Company-years</th></tr></thead>
            <tbody>{best.map((b) => {
              const hm = b.ranked.find((x) => x.model === "HYBRID MODEL");
              const two = b.ranked[1];
              return (
                <tr key={b.sector}>
                  <td className="sticky strong">{b.sector}</td>
                  <td><span className="row" style={{ gap: 6 }}><i className="fc-sw" style={{ background: colorOf(b.best) }} /><b className={b.best === "HYBRID MODEL" ? "hm" : ""}>{b.best}</b></span></td>
                  <td className="r mono up">{pctUnits(b.bestErr, 1)}</td>
                  <td className="r mono">{pctUnits(b.ranked[0].hit, 0)}</td>
                  <td className="muted">{two ? <>{two.model} <span className="mono faint">{pctUnits(two.err, 0)}</span></> : "—"}</td>
                  <td className="r mono" style={{ color: HM_COLOR }}>{hm ? pctUnits(hm.err, 1) : "—"}</td>
                  <td className="r mono faint">{b.n}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Sectors won, by model" meta="most accurate in">
        <ResponsiveContainer width="100%" height={Math.max(160, wins.length * 30)}>
          <BarChart data={wins} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
            <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={{ stroke: "var(--line)" }} />
            <YAxis type="category" dataKey="model" width={130} tickLine={false} axisLine={false} tick={{ fill: "var(--fg)", fontSize: 11 }} />
            <Tooltip content={<Tip fmt={(x) => `${x} sector${x === 1 ? "" : "s"}`} />} cursor={{ fill: "var(--hover)" }} />
            <Bar dataKey="sectors" name="Sectors" radius={[0, 3, 3, 0]} barSize={12}>{wins.map((w) => <Cell key={w.model} fill={colorOf(w.model)} />)}</Bar>
          </BarChart>
        </ResponsiveContainer>
      </Panel>
    </div>
  );
}

function ErrorMatrix({ best }: { best: ReturnType<typeof bestBySector> }) {
  const models = [...new Set(best.flatMap((b) => b.ranked.map((r) => r.model)))];
  return (
    <Panel title="Error by sector and model" meta="median absolute % error · darker = worse · outlined = best in the sector" flush>
      <div className="dg-wrap">
        <table className="dg dense">
          <thead><tr><th className="sticky">Sector</th>{models.map((mm) => <th key={mm} className="r" style={mm === "HYBRID MODEL" ? { color: HM_COLOR } : undefined}>{mm}</th>)}</tr></thead>
          <tbody>{best.map((b) => (
            <tr key={b.sector}>
              <td className="sticky strong">{b.sector}</td>
              {models.map((mm) => {
                const v = b.ranked.find((x) => x.model === mm)?.err;
                return <td key={mm} className="r"><span className={`heat ${mm === b.best ? "best" : ""}`} style={{ background: `rgba(239,135,115,${isNum(v) ? Math.min(0.55, v / 150) : 0})` }}>{pctUnits(v, 0)}</span></td>;
              })}
            </tr>
          ))}</tbody>
        </table>
      </div>
    </Panel>
  );
}

function SectorForecastTable({ fc, models }: { fc: SectorForecast[]; models: string[] }) {
  const [lens, setLens] = useState<SectorLens>("upside");
  const used = models.filter((mm) => fc.some((s) => (s.byModel[mm]?.n ?? 0) > 0));
  return (
    <Panel title="Sector valuation forecast, by model" flush
      meta={lens === "upside" ? "median of each model's value against today's price" : "median projected price move over the next year"}
      tools={<div className="seg"><button className={lens === "upside" ? "on" : ""} onClick={() => setLens("upside")}>Value vs price</button><button className={lens === "move" ? "on" : ""} onClick={() => setLens("move")}>1-year projection</button></div>}>
      <div className="dg-wrap">
        <table className="dg dense">
          <thead><tr><th className="sticky">Sector</th><th className="r">Cos</th>{used.map((mm) => <th key={mm} className="r" style={mm === "HYBRID MODEL" ? { color: HM_COLOR } : undefined}>{mm.replace(/ Valuation$/, "")}</th>)}<th className="r">All models</th></tr></thead>
          <tbody>{fc.map((s) => (
            <tr key={s.sector}>
              <td className="sticky strong">{s.sector}</td>
              <td className="r mono faint">{s.companies}</td>
              {used.map((mm) => {
                const x = s.byModel[mm]?.[lens];
                return <td key={mm} className="r"><span className="heat" style={{ background: upColor(x) }} title={`${s.byModel[mm]?.n ?? 0} companies`}>{pct(x, 0, true)}</span></td>;
              })}
              <td className="r"><b className={`mono ${((lens === "upside" ? s.consensusUpside : s.consensusMove) ?? 0) >= 0 ? "up" : "down"}`}>{pct(lens === "upside" ? s.consensusUpside : s.consensusMove, 0, true)}</b></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="fc-note xs faint"><Icon name="info" className="xs" />Green: the model values the sector above today's price; red: below. The 1-year projection assumes prices keep closing each model's gap at the pace they have in the report — a projection from history, not advice.</div>
    </Panel>
  );
}

function Segregation({ fc }: { fc: SectorForecast[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const chart = fc.filter((s) => isNum(s.consensusUpside)).map((s) => ({ sector: s.sector, upside: s.consensusUpside, move: s.consensusMove }));
  return (
    <div className="grid c2">
      <Panel title="Sector segregation" meta={`companies below, near (±${Math.round(NEAR_BAND * 100)}%) and above the models' value`} flush>
        <div className="dg-wrap">
          <table className="dg dense">
            <thead><tr><th className="sticky">Sector</th><th style={{ width: "22%", minWidth: 120 }}>Below · near · above</th><th className="r">Upside</th><th className="r">1-year view</th><th>Top pick</th></tr></thead>
            <tbody>{fc.map((s) => {
              const n = Math.max(1, s.below + s.near + s.above);
              return (
                <Fragment key={s.sector}>
                  <tr className="click" onClick={() => setOpen(open === s.sector ? null : s.sector)}>
                    <td className="sticky strong"><span className="row" style={{ gap: 6 }}><Icon name={open === s.sector ? "chevron-down" : "chevron-right"} className="xs faint" />{s.sector}</span></td>
                    <td><div className="seg-bar" title={`${s.below} below value · ${s.near} near · ${s.above} above`}>
                      <i style={{ width: `${(100 * s.below) / n}%`, background: "var(--up)" }} /><i style={{ width: `${(100 * s.near) / n}%`, background: "var(--c-blue)" }} /><i style={{ width: `${(100 * s.above) / n}%`, background: "var(--down)" }} />
                    </div><span className="xs faint">{s.below} · {s.near} · {s.above}</span></td>
                    <td className={`r mono ${(s.consensusUpside ?? 0) >= 0 ? "up" : "down"}`}>{pct(s.consensusUpside, 0, true)}</td>
                    <td className={`r mono ${(s.consensusMove ?? 0) >= 0 ? "up" : "down"}`}>{pct(s.consensusMove, 1, true)}</td>
                    <td className="ellipsis" style={{ maxWidth: 200 }}>{s.names[0] ? <Link to={companyPath(s.names[0].company)} onClick={(e) => e.stopPropagation()}>{shortName(s.names[0].company)}</Link> : "—"}</td>
                  </tr>
                  {open === s.sector && (
                    <tr className="analyst-row"><td colSpan={5} style={{ whiteSpace: "normal", padding: "8px 12px 12px" }}>
                      <div className="sec-names">{s.names.map((x) => (
                        <Link key={x.company} to={companyPath(x.company)} className="sec-name">
                          <span className="ellipsis">{shortName(x.company)}</span>
                          <b className={`mono ${x.upside >= 0 ? "up" : "down"}`}>{pct(x.upside, 0, true)}</b>
                        </Link>
                      ))}</div>
                    </td></tr>
                  )}
                </Fragment>
              );
            })}</tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Sector prediction" meta="median across models · value vs price, and the 1-year projection">
        <ResponsiveContainer width="100%" height={Math.max(220, chart.length * 30)}>
          <BarChart data={chart} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="2 4" horizontal={false} />
            <XAxis type="number" tickFormatter={(x) => pct(x, 0, true)} tickLine={false} axisLine={{ stroke: "var(--line)" }} />
            <YAxis type="category" dataKey="sector" width={170} tickLine={false} axisLine={false} tick={{ fill: "var(--fg)", fontSize: 11 }} />
            <ReferenceLine x={0} stroke="var(--fg-3)" />
            <Tooltip content={<Tip fmt={(x) => pct(x as number, 1, true)} />} cursor={{ fill: "var(--hover)" }} />
            <Legend />
            <Bar dataKey="upside" name="Value vs price" barSize={9} radius={2} fill="#86CF86">{chart.map((c) => <Cell key={c.sector} fill={(c.upside ?? 0) >= 0 ? "#86CF86" : "#EF8773"} />)}</Bar>
            <Bar dataKey="move" name="1-year projection" barSize={9} radius={2} fill="#57A3F8" />
          </BarChart>
        </ResponsiveContainer>
      </Panel>
    </div>
  );
}

// ================================================================ one company
type View = "models" | "hybrid" | "ensemble";
function CompanyTab({ d }: { d: Valuation }) {
  const [params, setParams] = useSearchParams();
  const raw = params.get("view") ?? (params.get("tab") === "hybrid" ? "hybrid" : params.get("tab") === "ensemble" ? "ensemble" : "models");
  const view = (["models", "hybrid", "ensemble"].includes(raw) ? raw : "models") as View;
  const set = (v: View) => { const p = new URLSearchParams(params); p.set("tab", "company"); p.set("view", v); setParams(p, { replace: true }); };
  return (
    <>
      <div className="seg" style={{ alignSelf: "flex-start" }}>
        <button className={view === "models" ? "on" : ""} onClick={() => set("models")}>Every model</button>
        <button className={view === "hybrid" ? "on" : ""} onClick={() => set("hybrid")}>HYBRID MODEL detail</button>
        <button className={view === "ensemble" ? "on" : ""} onClick={() => set("ensemble")}>Ensemble detail</button>
      </div>
      {view === "models" && <Explore d={d} />}
      {view === "hybrid" && <HybridDetail d={d} />}
      {view === "ensemble" && <EnsembleDetail d={d} />}
    </>
  );
}

/** Everything a valuation run writes: the files to download, the charts it drew and who it left out. */
function FilesTab() {
  const ex = useExcluded();
  const scope = useScope();
  const left = (ex.data?.rows ?? []).filter((r) => scope.has({ company: String(r["Company name"] ?? "") })).length;
  return (
    <>
      <Panel title="Downloads" meta="every file the last valuation run wrote" flush><Files /></Panel>
      <Panel title="Charts" meta="drawn by the analysis stage of a valuation run"><Gallery /></Panel>
      <Panel title="Left out of the last report" meta={ex.data ? (left ? `${left} compan${left === 1 ? "y" : "ies"} without enough data` : "nobody") : undefined} flush><Excluded /></Panel>
    </>
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
    <Select value={c.company} onChange={c.set} style={{ minWidth: 280 }} ariaLabel="Company" options={c.companies.map((x) => ({ value: x, label: shortName(x), text: x }))} />
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

/** What a chart file is, in words, and which group it belongs to. */
function chartInfo(file: string) {
  const base = file.replace(/\.png$/, "");
  const m = base.match(/^sector_(.+)_(levels|normalised)$/);
  if (m) return { group: "sector", title: `${titleCase(m[1].replace(/_/g, " "))}`, sub: m[2] === "levels" ? "every model against the price, per company" : "values relative to the price" , kind: m[2] };
  return { group: "overview", title: titleCase(base.replace(/_/g, " ")), sub: "across every company", kind: "overview" };
}
const CHART_GROUPS = [["all", "All"], ["overview", "Overview"], ["levels", "Sectors · against the price"], ["normalised", "Sectors · relative to the price"]] as const;

function Gallery() {
  const q = useCharts();
  const [open, setOpen] = useState<number | null>(null);
  const [group, setGroup] = useState<(typeof CHART_GROUPS)[number][0]>("all");
  const [find, setFind] = useState("");
  return (
    <QueryView q={q}>
      {(names) => {
        if (!names.length) return <Empty icon="file-media" title="No charts yet">The analysis stage of a valuation run draws them.</Empty>;
        const all = names.map((n) => ({ src: `/api/charts/${n}`, ...chartInfo(n) }));
        const shown = all.filter((c) => (group === "all" || c.kind === group || (group === "overview" && c.group === "overview"))
          && (!find || `${c.title} ${c.sub}`.toLowerCase().includes(find.toLowerCase())));
        const images = shown.map((c) => ({ src: c.src, title: c.group === "sector" ? `${c.title} — ${c.sub}` : c.title }));
        return (
          <div className="fc">
            <div className="fc-bar">
              <div className="seg" role="group" aria-label="Show charts">
                {CHART_GROUPS.map(([k, l]) => {
                  const n = k === "all" ? all.length : all.filter((c) => c.kind === k || (k === "overview" && c.group === "overview")).length;
                  return n || k === "all" ? <button key={k} className={group === k ? "on" : ""} aria-pressed={group === k} onClick={() => setGroup(k)}>{l}<span className="fc-n">{n}</span></button> : null;
                })}
              </div>
              <label className="search fc-find"><Icon name="search" /><input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find a chart or sector" aria-label="Find a chart or sector" /></label>
            </div>
            {!shown.length ? <p className="fc-none">No chart matches “{find}”.</p> : (
              <ul className="fc-grid">
                {shown.map((c, i) => (
                  <li key={c.src}>
                    <button className="fc-card" onClick={() => setOpen(i)} aria-label={`Open the chart: ${images[i].title}`}>
                      <span className="fc-img"><img src={c.src} alt="" loading="lazy" /></span>
                      <span className="fc-t"><b>{c.title}</b><small>{c.sub}</small></span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {open != null && images.length > 0 && <ImageViewer images={images} index={Math.min(open, images.length - 1)} onIndex={setOpen} onClose={() => setOpen(null)} />}
          </div>
        );
      }}
    </QueryView>
  );
}

function Excluded() {
  const q = useExcluded();
  const scope = useScope();
  return (
    <QueryView q={q}>
      {(all) => { const d = { ...all, rows: all.rows.filter((r) => scope.has({ company: String(r["Company name"] ?? "") })) }; return !d.rows.length ? <Empty icon="pass" title="Every company was used">Nobody was left out of the last report for missing data.</Empty> : (
        <div className="dg-wrap">
          <table className="dg">
            <thead><tr><th>Company</th><th>Problem</th><th>What went wrong</th><th>What you can do</th></tr></thead>
            <tbody>{d.rows.map((r, i) => <tr key={i}><td className="strong">{r["Company name"]}</td><td><span className="tag warn">{r["Type of problem"]}</span></td><td style={{ whiteSpace: "normal" }} className="small">{r["In plain words, what went wrong"]}</td><td style={{ whiteSpace: "normal" }} className="small muted">{r["What you can do about it"]}</td></tr>)}</tbody>
          </table>
        </div>
      ); }}
    </QueryView>
  );
}

/** A file the report writes, in words, and the group it belongs to. */
const FILE_INFO: [RegExp, string, string][] = [
  [/^Intrinsic_Value_Report\.xlsx$/, "report", "The valuation report · Excel workbook"],
  [/^Intrinsic_Value_Report\.csv$/, "report", "The valuation report · CSV"],
  [/^analysis_report\.html$/, "report", "The analysis report · web page with every chart"],
  [/^Intrinsic_Value_Data\.csv$/, "report", "The numbers behind the report"],
  [/^metrics_overall\.csv$/, "metrics", "Accuracy of every model"],
  [/^metrics_by_(\w+)\.csv$/, "metrics", "Accuracy by $1"],
  [/^metrics_win_rate\.csv$/, "metrics", "Which model came closest, how often"],
  [/^analysis_summary\.json$/, "metrics", "Analysis summary · JSON"],
  [/^Hybrid_Model_Detail\.csv$/, "models", "HYBRID MODEL · every lens, weight and band"],
  [/^hybrid_model_bases\.json$/, "models", "HYBRID MODEL · each company's latest inputs"],
  [/^Ensemble_Detail\.csv$/, "models", "Ensemble · weights and components"],
  [/^ml_metrics\.csv$/, "models", "AI models · accuracy per year"],
  [/^ml_feature_importance\.csv$/, "models", "AI models · what they rely on"],
  [/^ml_dataset\.csv$/, "models", "AI models · the training rows"],
  [/^Intrinsic_Value_Diagnostics\.csv$/, "quality", "Why some cells are blank"],
  [/^Intrinsic_Value_Methods\.csv$/, "quality", "How each value was worked out"],
  [/^Intrinsic_Value_Excluded\.csv$|^Why_Companies_Were_Left_Out\.csv$/, "quality", "Companies left out, and why"],
  [/^Why_Companies_Were_Left_Out_By_Year\.csv$/, "quality", "Companies left out, year by year"],
  [/^run_log\.txt$/, "other", "The last run's full log"],
];
const FILE_GROUPS: [string, string][] = [["report", "The report"], ["metrics", "Accuracy"], ["models", "Model detail"], ["quality", "Data quality"], ["other", "Other files"]];
function fileInfo(file: string) {
  for (const [re, group, label] of FILE_INFO) { const m = file.match(re); if (m) return { group, label: label.replace("$1", m[1] ?? "") }; }
  return { group: "other", label: titleCase(file.replace(/\.[a-z]+$/, "").replace(/_/g, " ")) };
}

function Files() {
  const q = useDownloads();
  return (
    <QueryView q={q}>
      {(files) => !files.length ? <Empty icon="files" title="No files yet">A valuation run writes them.</Empty> : (
        <div className="fd">
          {FILE_GROUPS.map(([g, title]) => {
            const mine = files.map((f) => ({ f, ...fileInfo(f.file) })).filter((x) => x.group === g);
            if (!mine.length) return null;
            return (
              <section key={g} className="fd-g" aria-labelledby={`fd-${g}`}>
                <h4 id={`fd-${g}`}>{title}</h4>
                <ul>
                  {mine.map(({ f, label }) => {
                    const ext = (f.file.split(".").pop() ?? "").toUpperCase();
                    return (
                      <li key={f.key} className="fd-row">
                        <span className={`fd-ext x-${ext.toLowerCase()}`} aria-hidden="true">{ext}</span>
                        <span className="fd-n"><b>{label}</b><small className="mono">{f.file}</small></span>
                        <span className="fd-m">{ago(f.updated)} · {bytes(f.size)}</span>
                        <a className="btn xs sec" href={`/api/downloads/${f.key}`} download aria-label={`Download ${label} (${f.file})`}><Icon name="desktop-download" className="xs" />Download</a>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </QueryView>
  );
}
