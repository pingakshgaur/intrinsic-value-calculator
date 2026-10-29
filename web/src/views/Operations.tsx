import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useCompanies, useJobs, usePrefs, useStartJob, useStatus } from "../lib/hooks";
import { useLearning, useWatchlists } from "../lib/live";
import { JobSummary } from "../lib/api";
import { duration, when } from "../lib/format";
import { Drawer, ErrorNote, Icon, PageHeader, Panel, Toggle } from "../components/ui";
import { Column, DataGrid, useGridState } from "../components/DataGrid";
import { RunMonitor } from "../components/JobLog";
import { jobTitle } from "../components/Shell";
import { useApp } from "../components/workbenchContext";

type Kind = "valuation" | "research" | "learn" | "screen";
const KINDS: { id: Kind; icon: string; t: string; d: string }[] = [
  { id: "valuation", icon: "graph", t: "Valuation report", d: "Every model, every year, scored against the market" },
  { id: "research", icon: "rocket", t: "Research", d: "The agents read news, filings and the market" },
  { id: "learn", icon: "cloud-download", t: "Refresh training data", d: "Fetch accounts for every company the models learn from" },
  { id: "screen", icon: "filter", t: "Data check", d: "Who has enough data - values nothing" },
];
type Scope = "all" | "list" | "pick";
const EXCL = "ops.excluded.v1";
const STATUS_DOT: Record<string, string> = { running: "busy", queued: "busy", succeeded: "ok", failed: "bad" };

/** Start any job from one form, and follow every job live. Each job is its own process: closing the browser does not stop it. */
export function Operations() {
  const [params, setParams] = useSearchParams();
  const companies = useCompanies();
  const lib = useWatchlists();
  const prefs = usePrefs();
  const status = useStatus();
  const jobs = useJobs(!!status.data?.active_job);
  const learning = useLearning();
  const start = useStartJob();
  const app = useApp();
  const [kind, setKind] = useState<Kind>("valuation");
  const [scope, setScope] = useState<Scope>("all");
  const [listId, setListId] = useState("");
  const [excluded, setExcluded] = useState<Set<string>>(() => { try { return new Set(JSON.parse(localStorage.getItem(EXCL) || "[]")); } catch { return new Set(); } });
  const [picker, setPicker] = useState(false);
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [quick, setQuick] = useState(true);
  const [learnToo, setLearnToo] = useState<boolean | null>(null);
  const [retrain, setRetrain] = useState(false);
  const [more, setMore] = useState(false);
  const [offline, setOffline] = useState(false);
  const [noLlm, setNoLlm] = useState(false);
  const [auto, setAuto] = useState(false);
  const [ao, setAo] = useState({ target: 60, max: 100, sectors: 10, min_listed_years: 10 });
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { try { localStorage.setItem(EXCL, JSON.stringify([...excluded])); } catch { /* ignore */ } }, [excluded]);
  useEffect(() => { if (prefs.data && from == null) { setFrom(prefs.data.values.start_year); setTo(prefs.data.values.end_year); } }, [prefs.data, from]);

  const list = companies.data ?? [];
  const lists = (lib.data?.lists ?? []).filter((l) => l.count > 0);
  const chosenList = lists.find((l) => l.id === listId) ?? lists[0];
  const included = list.filter((c) => !excluded.has(c.name));
  const ceiling = prefs.data?.latest_fy ?? new Date().getFullYear();
  const active = status.data?.active_job;
  const selected = params.get("job") ?? active?.id ?? jobs.data?.[0]?.id ?? null;
  const p = prefs.data?.values;
  const span = from && to ? Math.abs(to - from) + 1 : 0;
  const learnCompanies = learning.data?.companies;
  const useLearn = learnToo ?? learning.data?.settings.use_in_runs ?? true;
  const warn: string[] = [];
  if (from && to && Math.max(from, to) > ceiling) warn.push(`FY${Math.max(from, to)} has not ended — it will be trimmed to FY${ceiling}.`);
  if (span && span < 3) warn.push("Fewer than 3 years leaves the AI models little to learn from.");

  const count = kind === "learn" ? learnCompanies ?? 0 : scope === "list" ? chosenList?.count ?? 0 : scope === "pick" ? included.length : list.length;
  const what = kind === "research" ? (quick ? "Quick sweep" : "Full research") : KINDS.find((k) => k.id === kind)!.t;

  const launch = () => {
    setErr(null);
    if (kind !== "learn" && scope === "pick" && !included.length && !offline) return setErr(new Error("Every company is unticked — include at least one."));
    if (kind !== "learn" && scope === "list" && !chosenList) return setErr(new Error("There is no watchlist with companies yet."));
    const target: Record<string, unknown> = kind === "learn" || offline ? {} : scope === "list" ? { watchlist: chosenList!.id }
      : scope === "pick" && excluded.size ? (kind === "research" ? { tickers: included.map((c) => (c.ticker || "").split(".")[0]).filter(Boolean).join(",") } : { exclude: [...excluded] }) : {};
    const options: Record<string, unknown> = kind === "research" ? { quick, offline, no_llm: noLlm, ...target }
      : kind === "learn" ? { start_year: from, end_year: to, retrain }
      : { offline, start_year: from, end_year: to, ...target, ...(kind === "valuation" ? (auto ? { auto_train: ao } : { learning: useLearn }) : {}) };
    start.mutate({ kind: kind === "research" ? "agents" : kind, options }, {
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
  const years = kind !== "research";

  return (
    <div className="page">
      <PageHeader crumbs={[{ label: "Operations" }]} title="Operations" sub="Start a job and follow it live. Each job runs on its own — closing the browser does not stop it."
        actions={<Link to="/configuration?section=run" className="btn sec"><Icon name="settings" className="sm" />Run settings</Link>} />
      <div className="ops">
        <Panel title="New job" flush>
          <div className="form-sec">
            <div className="fh"><span className="num">1</span><b>What to run</b></div>
            <div className="jobtype">
              {KINDS.map((k) => <button key={k.id} className={`jt ${kind === k.id ? "on" : ""}`} onClick={() => setKind(k.id)} aria-pressed={kind === k.id}><b><Icon name={k.icon} className="sm" />{k.t}</b><span>{k.d}</span></button>)}
            </div>
            {kind === "research" && (
              <div className="seg" style={{ alignSelf: "flex-start" }}>
                <button className={quick ? "on" : ""} onClick={() => setQuick(true)}><Icon name="zap" className="xs" />Quick sweep · news and market</button>
                <button className={!quick ? "on" : ""} onClick={() => setQuick(false)}><Icon name="rocket" className="xs" />Full research · all 23 agents</button>
              </div>
            )}
          </div>

          <div className="form-sec">
            <div className="fh"><span className="num">2</span><b>Companies</b></div>
            {kind === "learn" ? <span className="small muted">Every company the models learn from: {learnCompanies ?? "…"} (the training lists and every watchlist).</span> : (
              <>
                <div className="seg" style={{ alignSelf: "flex-start" }}>
                  <button className={scope === "all" ? "on" : ""} onClick={() => setScope("all")}>All covered ({list.length})</button>
                  <button className={scope === "list" ? "on" : ""} onClick={() => setScope("list")} disabled={!lists.length} title={!lists.length ? "No watchlist has companies yet" : undefined}>A watchlist</button>
                  <button className={scope === "pick" ? "on" : ""} onClick={() => { setScope("pick"); setPicker(true); }}>Pick…</button>
                </div>
                {scope === "list" && chosenList && (
                  <select className="sel" value={chosenList.id} onChange={(e) => setListId(e.target.value)} style={{ maxWidth: 360 }}>
                    {lists.map((l) => <option key={l.id} value={l.id}>{l.name} ({l.count})</option>)}
                  </select>
                )}
                {scope === "pick" && <div className="row small"><span className="strong">{included.length}</span><span className="muted">of {list.length} covered companies</span><button className="btn xs sec" onClick={() => setPicker(true)}><Icon name="checklist" className="xs" />Change</button></div>}
                {scope === "list" && <span className="xs faint">Every company on the list is included, valued before or not — its accounts are fetched when needed.</span>}
              </>
            )}
          </div>

          <div className="form-sec">
            <div className="fh"><span className="num">3</span><b>Years</b></div>
            {!years ? <span className="muted small">Research values the latest complete year (FY{ceiling}).</span> : (
              <>
                <div className="row">
                  <label className="fld" style={{ width: 90 }}><span>From FY</span><input className="inp num" inputMode="numeric" value={from ?? ""} onChange={(e) => setFrom(Number(e.target.value.replace(/\D/g, "").slice(0, 4)) || null)} /></label>
                  <label className="fld" style={{ width: 90 }}><span>To FY</span><input className="inp num" inputMode="numeric" value={to ?? ""} onChange={(e) => setTo(Number(e.target.value.replace(/\D/g, "").slice(0, 4)) || null)} /></label>
                  <div className="seg" style={{ marginTop: 18 }}><button onClick={() => { setTo(ceiling); setFrom(ceiling - 4); }}>Last 5</button><button onClick={() => { setTo(ceiling); setFrom(ceiling - 9); }}>Last 10</button></div>
                </div>
                {from && to && <span className="xs info">{span} financial year{span === 1 ? "" : "s"}: April {Math.min(from, to) - 1} to March {Math.max(from, to)}</span>}
                {warn.map((w, i) => <span key={i} className="xs warn row"><Icon name="warning" className="xs" />{w}</span>)}
              </>
            )}
          </div>

          <div className="form-sec">
            <div className="fh"><span className="num">4</span><b>Options</b><span className="spacer" />
              {kind !== "learn" && <button className="btn xs ghost" onClick={() => setMore(!more)} aria-expanded={more}><Icon name={more ? "chevron-up" : "chevron-down"} className="xs" />More options</button>}</div>
            {kind === "valuation" && <Toggle checked={useLearn && !auto} disabled={auto} onChange={setLearnToo} label={`Also learn from the ${learnCompanies ?? "…"} training companies (better models, longer run)`} />}
            {kind === "learn" && <Toggle checked={retrain} onChange={setRetrain} label="Then retrain the models on the fresh data" />}
            {kind === "research" && <span className="small muted">Uses the AI providers set up in Configuration when they have a key; rule-based otherwise.</span>}
            {kind === "screen" && <span className="small muted">Settings in use: {p ? (p.screening === "off" ? "no data gate" : `${p.min_complete_fy}+ complete years required`) : "…"}.</span>}
            {more && kind !== "learn" && (
              <div className="fieldset col" style={{ gap: 10 }}>
                {kind === "valuation" && <Toggle checked={auto} onChange={setAuto} label="Auto-train: keep adding market companies until the Ensemble is confident" />}
                {kind === "valuation" && auto && (
                  <div className="row wrap" style={{ gap: 10 }}>
                    {([["target", "Target confidence", 5, 95], ["max", "Most companies", 5, 1000], ["sectors", "Top sectors", 1, 25], ["min_listed_years", "Listed ≥ years", 1, 30]] as const).map(([k, l, lo, hi]) => (
                      <label key={k} className="fld"><span>{l}</span><input className="inp sm num" type="number" min={lo} max={hi} value={ao[k]} onChange={(e) => setAo({ ...ao, [k]: Math.max(lo, Math.min(hi, Number(e.target.value) || lo)) })} /></label>
                    ))}
                  </div>
                )}
                {kind === "research" && <Toggle checked={noLlm} onChange={setNoLlm} label="Rule-based only (no AI calls)" />}
                <Toggle checked={offline} onChange={setOffline} label="Offline test data (no internet; ignores the companies above)" />
              </div>
            )}
          </div>

          <div className="form-sec">
            {err != null && <ErrorNote error={err} />}
            <button className="btn" style={{ height: 36 }} onClick={launch} disabled={!!active || start.isPending}>
              <Icon name={start.isPending ? "loading" : "play"} className={start.isPending ? "spin" : ""} />Start {what.toLowerCase()}{count ? ` · ${count} compan${count === 1 ? "y" : "ies"}` : ""}
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
        <div className="seg"><button onClick={() => setExcluded(new Set())}>All</button><button onClick={() => setExcluded(new Set(list.map((c) => c.name)))}>None</button></div>
      </div>
      <div className="row wrap" style={{ gap: 6 }}>
        {sectors.map((s) => {
          const names = list.filter((c) => c.sector === s).map((c) => c.name);
          const allOn = names.every((n) => !excluded.has(n));
          return <button key={s} className={`chip ${allOn ? "on" : ""}`} onClick={() => { const x = new Set(excluded); names.forEach((n) => (allOn ? x.add(n) : x.delete(n))); setExcluded(x); }}>{s}<span className="faint">{names.length}</span></button>;
        })}
      </div>
      <div className="panel" style={{ overflow: "auto" }}>
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
