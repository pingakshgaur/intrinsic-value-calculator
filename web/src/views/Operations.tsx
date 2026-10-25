import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useCompanies, useJobs, usePrefs, useStartJob, useStatus } from "../lib/hooks";
import { useLearning } from "../lib/live";
import { JobSummary } from "../lib/api";
import { duration, when } from "../lib/format";
import { Drawer, ErrorNote, Icon, PageHeader, Panel, Toggle } from "../components/ui";
import { Column, DataGrid, useGridState } from "../components/DataGrid";
import { RunMonitor } from "../components/JobLog";
import { jobTitle } from "../components/Shell";
import { useApp } from "../components/workbenchContext";

type Kind = "valuation" | "screen" | "research" | "quick" | "learn";
const KINDS: { id: Kind; icon: string; t: string; d: string }[] = [
  { id: "valuation", icon: "graph", t: "Valuation report", d: "All models, every year, HYBRID MODEL, workbook, metrics" },
  { id: "research", icon: "rocket", t: "Full research", d: "HYBRID MODEL + all 23 agents" },
  { id: "quick", icon: "zap", t: "Quick sweep", d: "News & market agents only" },
  { id: "learn", icon: "mortar-board", t: "Learning feed", d: "Fetch accounts of every training & watchlist company" },
  { id: "screen", icon: "filter", t: "Data check", d: "Sufficiency screen; values nothing" },
];
const EXCL = "ops.excluded.v1";
const STATUS_DOT: Record<string, string> = { running: "busy", queued: "busy", succeeded: "ok", failed: "bad" };

export function Operations() {
  const [params, setParams] = useSearchParams();
  const companies = useCompanies();
  const prefs = usePrefs();
  const status = useStatus();
  const jobs = useJobs(!!status.data?.active_job);
  const start = useStartJob();
  const app = useApp();
  const [kind, setKind] = useState<Kind>("valuation");
  const [excluded, setExcluded] = useState<Set<string>>(() => { try { return new Set(JSON.parse(localStorage.getItem(EXCL) || "[]")); } catch { return new Set(); } });
  const [picker, setPicker] = useState(false);
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [offline, setOffline] = useState(false);
  const [noLlm, setNoLlm] = useState(false);
  const [auto, setAuto] = useState(false);
  const [ao, setAo] = useState({ target: 60, max: 100, sectors: 10, min_listed_years: 10 });
  const learning = useLearning();
  const [learn, setLearn] = useState<boolean | null>(null);
  const [retrain, setRetrain] = useState(false);
  const useLearn = learn ?? learning.data?.settings.use_in_runs ?? true;
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { try { localStorage.setItem(EXCL, JSON.stringify([...excluded])); } catch { /* ignore */ } }, [excluded]);
  useEffect(() => { if (prefs.data && from == null) { setFrom(prefs.data.values.start_year); setTo(prefs.data.values.end_year); } }, [prefs.data, from]);

  const list = companies.data ?? [];
  const included = list.filter((c) => !excluded.has(c.name));
  const ceiling = prefs.data?.latest_fy ?? new Date().getFullYear();
  const research = kind === "research" || kind === "quick";
  const active = status.data?.active_job;
  const selected = params.get("job") ?? active?.id ?? jobs.data?.[0]?.id ?? null;
  const p = prefs.data?.values;
  const span = from && to ? Math.abs(to - from) + 1 : 0;
  const warn: string[] = [];
  if (from && to && Math.max(from, to) > ceiling) warn.push(`FY${Math.max(from, to)} has not ended — it will be trimmed to FY${ceiling}.`);
  if (span && span < 3) warn.push("Fewer than 3 years leaves the AI models little to learn from.");
  if (from && to && Math.min(from, to) < ceiling - 8) warn.push("The data source has about four years of accounts for most companies; early years will be thin.");

  const launch = () => {
    setErr(null);
    if (!included.length && !offline) return setErr(new Error("Every company is excluded — include at least one."));
    const options: Record<string, unknown> = research
      ? { offline, quick: kind === "quick", no_llm: noLlm, tickers: excluded.size ? included.map((c) => (c.ticker || "").split(".")[0]).filter(Boolean).join(",") : "" }
      : kind === "learn" ? { start_year: from, end_year: to, retrain }
      : { offline, exclude: [...excluded], start_year: from, end_year: to, ...(kind === "valuation" && auto ? { auto_train: ao } : {}),
          ...(kind === "valuation" && !auto ? { learning: useLearn } : {}) };
    start.mutate({ kind: research ? "agents" : kind, options }, {
      onSuccess: (j) => { setParams({ job: j.id }); app.toast(`${jobTitle(j.kind, j.opts)} started`); },
      onError: (e) => setErr(e),
    });
  };

  const cols: Column<JobSummary>[] = [
    { key: "status", header: "", fixed: true, width: 28, render: (j) => <span className={`dot ${STATUS_DOT[j.status] ?? ""}`} title={j.status} /> },
    { key: "job", header: "Job", fixed: true, sort: (j) => jobTitle(j.kind, j.opts), render: (j) => <span className="strong">{jobTitle(j.kind, j.opts)}</span> },
    { key: "state", header: "Status", sort: (j) => j.status, render: (j) => <span className={`tag ${j.status === "failed" ? "down" : j.status === "succeeded" ? "up" : ""}`}>{j.status}</span> },
    { key: "started", header: "Started", sort: (j) => j.started, render: (j) => <span className="muted">{when(j.started)}</span> },
    { key: "dur", header: "Duration", align: "r", sort: (j) => (j.finished ?? Date.now() / 1000) - j.started, render: (j) => <span className="mono muted">{duration((j.finished ?? Date.now() / 1000) - j.started)}</span> },
    { key: "id", header: "ID", visible: false, render: (j) => <span className="mono faint">{j.id}</span> },
  ];
  const gstate = useGridState<JobSummary>("ops-jobs", cols, { key: "started", asc: false });

  return (
    <div className="page">
      <PageHeader crumbs={[{ label: "Operations" }]} title="Operations" sub="Launch valuation and research jobs and follow them live. Each job is its own process — closing the browser does not stop it."
        actions={<Link to="/configuration?section=run" className="btn sec"><Icon name="settings" className="sm" />Run settings</Link>} />
      <div className="ops">
        <Panel title="New job" flush>
          <div className="form-sec">
            <div className="fh"><span className="num">1</span><b>Job type</b></div>
            <div className="jobtype">
              {KINDS.map((k) => <button key={k.id} className={`jt ${kind === k.id ? "on" : ""}`} onClick={() => setKind(k.id)}><b><Icon name={k.icon} className="sm" />{k.t}</b><span>{k.d}</span></button>)}
            </div>
          </div>
          <div className="form-sec">
            <div className="fh"><span className="num">2</span><b>Scope</b><span className="spacer" /><button className="btn xs sec" onClick={() => setPicker(true)}><Icon name="checklist" className="xs" />Select companies</button></div>
            <div className="row small"><span className="strong">{included.length}</span><span className="muted">of {list.length} companies included</span>{excluded.size > 0 && <button className="btn xs ghost" onClick={() => setExcluded(new Set())}>Include all</button>}</div>
          </div>
          <div className="form-sec">
            <div className="fh"><span className="num">3</span><b>Period</b></div>
            {research ? <span className="muted small">Research values the latest complete year (FY{ceiling}) with {p ? p.end_year - p.start_year + 1 : 5} years of history.</span> : (
              <>
                <div className="row">
                  <label className="fld" style={{ width: 90 }}><span>From FY</span><input className="inp num" inputMode="numeric" value={from ?? ""} onChange={(e) => setFrom(Number(e.target.value.replace(/\D/g, "").slice(0, 4)) || null)} /></label>
                  <label className="fld" style={{ width: 90 }}><span>To FY</span><input className="inp num" inputMode="numeric" value={to ?? ""} onChange={(e) => setTo(Number(e.target.value.replace(/\D/g, "").slice(0, 4)) || null)} /></label>
                  <div className="col" style={{ gap: 4, marginTop: 18 }}>
                    <div className="seg"><button onClick={() => { setTo(ceiling); setFrom(ceiling - 4); }}>Last 5</button><button onClick={() => { setTo(ceiling); setFrom(ceiling - 9); }}>Last 10</button></div>
                  </div>
                </div>
                {from && to && <span className="xs info">{span} financial year{span === 1 ? "" : "s"}: {Math.min(from, to) - 1}-{String(Math.min(from, to)).slice(-2)} to {Math.max(from, to) - 1}-{String(Math.max(from, to)).slice(-2)} (April–March, named by the year they end)</span>}
                {warn.map((w, i) => <span key={i} className="xs warn row"><Icon name="warning" className="xs" />{w}</span>)}
              </>
            )}
          </div>
          <div className="form-sec">
            <div className="fh"><span className="num">4</span><b>Options</b></div>
            {kind === "learn" && (
              <>
                <span className="small muted">Fetches and caches the accounts of the {learning.data?.companies ?? "…"} learning companies (training lists + watchlist) for the period above, so valuation runs can train on them without downloading.</span>
                <Toggle checked={retrain} onChange={setRetrain} label="Then retrain: run the valuation report on the learning data" />
              </>
            )}
            {kind === "valuation" && (
              <>
                <Toggle checked={useLearn && !auto} disabled={auto} onChange={setLearn} label={`Train the ML models on the learning data too (${learning.data?.companies ?? "…"} more companies)`} />
                <Toggle checked={auto} onChange={setAuto} label="Auto-train on the live market until the Ensemble is confident" />
                {auto && (
                  <div className="fieldset">
                    {([["target", "Target confidence", 5, 95], ["max", "Most companies", 5, 1000], ["sectors", "Top sectors", 1, 25], ["min_listed_years", "Listed ≥ years", 1, 30]] as const).map(([k, l, lo, hi]) => (
                      <label key={k} className="fld"><span>{l}</span><input className="inp sm num" type="number" min={lo} max={hi} value={ao[k]} onChange={(e) => setAo({ ...ao, [k]: Math.max(lo, Math.min(hi, Number(e.target.value) || lo)) })} /></label>
                    ))}
                  </div>
                )}
              </>
            )}
            {research && <Toggle checked={noLlm} onChange={setNoLlm} label="Rule-based only (no AI calls)" />}
            <Toggle checked={offline} onChange={setOffline} label="Offline test data (no internet)" />
            {!research && p && <span className="xs faint">Settings in use: {p.screening === "off" ? "no data gate" : `${p.min_complete_fy}+ complete years`} · benchmark {p.benchmark_basis} · gaps {p.estimation} · ML {p.ml_enabled ? p.ml_split : "off"} · charts {p.analyze ? "on" : "off"}</span>}
          </div>
          <div className="form-sec">
            {err != null && <ErrorNote error={err} />}
            <button className="btn" style={{ height: 36 }} onClick={launch} disabled={!!active || start.isPending}>
              <Icon name={start.isPending ? "loading" : "play"} className={start.isPending ? "spin" : ""} />Launch {KINDS.find((k) => k.id === kind)!.t.toLowerCase()}
            </button>
            {active && <span className="xs muted">Waiting for “{jobTitle(active.kind, active.opts)}” to finish.</span>}
          </div>
        </Panel>

        <div className="col" style={{ gap: 14, minWidth: 0 }}>
          <Panel title="Job detail" meta={selected ? `#${selected}` : undefined}>
            <RunMonitor jobId={selected} />
          </Panel>
          <Panel title="Jobs" meta={`${jobs.data?.length ?? 0} recent`} flush>
            <DataGrid rows={jobs.data ?? []} columns={cols} rowKey={(j) => j.id} state={gstate} selected={selected} onSelect={(k) => setParams({ job: k })} empty="No jobs yet." maxHeight="360px" />
          </Panel>
        </div>
      </div>

      {picker && <CompanyPicker list={list} excluded={excluded} setExcluded={setExcluded} onClose={() => setPicker(false)} />}
    </div>
  );
}

function CompanyPicker({ list, excluded, setExcluded, onClose }: { list: { name: string; sector: string; cap: string; ticker: string }[]; excluded: Set<string>; setExcluded: (s: Set<string>) => void; onClose: () => void }) {
  const [f, setF] = useState("");
  const shown = useMemo(() => list.filter((c) => !f || `${c.name} ${c.sector} ${c.ticker}`.toLowerCase().includes(f.toLowerCase())), [list, f]);
  const sectors = useMemo(() => [...new Set(list.map((c) => c.sector))].sort(), [list]);
  const toggle = (n: string) => { const s = new Set(excluded); if (s.has(n)) s.delete(n); else s.add(n); setExcluded(s); };
  return (
    <Drawer title="Companies in this job" icon="checklist" wide onClose={onClose}
      footer={<><span className="muted small" style={{ marginRight: "auto" }}>{list.length - excluded.size} of {list.length} included</span><button className="btn" onClick={onClose}>Done</button></>}>
      <div className="row wrap">
        <div className="search grow"><Icon name="search" /><input value={f} onChange={(e) => setF(e.target.value)} placeholder="Filter" autoFocus /></div>
        <button className="btn sm sec" onClick={() => setExcluded(new Set())}>All</button>
        <button className="btn sm sec" onClick={() => setExcluded(new Set(list.map((c) => c.name)))}>None</button>
        <button className="btn sm sec" onClick={() => setExcluded(new Set(list.filter((c) => !excluded.has(c.name)).map((c) => c.name)))}>Invert</button>
      </div>
      <div className="row wrap" style={{ gap: 6 }}>
        {sectors.map((s) => {
          const names = list.filter((c) => c.sector === s).map((c) => c.name);
          const allOn = names.every((n) => !excluded.has(n));
          return <button key={s} className={`chip ${allOn ? "on" : ""}`} onClick={() => { const x = new Set(excluded); names.forEach((n) => (allOn ? x.add(n) : x.delete(n))); setExcluded(x); }}>{s}<span className="faint">{names.length}</span></button>;
        })}
      </div>
      <div className="panel" style={{ overflow: "hidden" }}>
        <table className="dg dense">
          <thead><tr><th style={{ width: 34 }} /><th>Company</th><th>Sector</th><th>Size</th><th>Ticker</th></tr></thead>
          <tbody>{shown.map((c) => (
            <tr key={c.name} className="click" onClick={() => toggle(c.name)} style={excluded.has(c.name) ? { opacity: 0.5 } : undefined}>
              <td><input type="checkbox" className="cb" checked={!excluded.has(c.name)} readOnly /></td>
              <td className="strong">{c.name}</td><td className="muted">{c.sector}</td><td className="muted">{c.cap}</td><td className="mono">{c.ticker}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </Drawer>
  );
}

