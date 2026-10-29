import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useCompanies, useJobs, usePrefs, useStartJob, useStatus } from "../lib/hooks";
import { useLearning, useWatchlists } from "../lib/live";
import { JobSummary } from "../lib/api";
import { duration, when } from "../lib/format";
import { ErrorNote, Icon, PageHeader, Panel, Popover, Toggle } from "../components/ui";
import { Column, DataGrid, useGridState } from "../components/DataGrid";
import { RunMonitor } from "../components/JobLog";
import { jobTitle } from "../components/Shell";
import { useApp } from "../components/workbenchContext";
import { Select } from "../components/Select";

type Kind = "valuation" | "research" | "learn" | "screen";
const KINDS: { id: Kind; icon: string; t: string; d: string }[] = [
  { id: "valuation", icon: "graph", t: "Valuation report", d: "Every model, every year, scored against the market" },
  { id: "research", icon: "rocket", t: "Research", d: "The agents read news, filings and the market" },
  { id: "learn", icon: "cloud-download", t: "Refresh training data", d: "Fetch accounts for every company the models learn from" },
  { id: "screen", icon: "filter", t: "Data check", d: "Who has enough data - values nothing" },
];
const ALL = "__all__";
const STATUS_DOT: Record<string, string> = { running: "busy", queued: "busy", succeeded: "ok", failed: "bad" };

/**
 * One form to start any job, then the job followed live and the recent jobs
 * below it. Each job is its own process: closing the browser does not stop it.
 */
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
  const [target, setTarget] = useState<string>(ALL);
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [quick, setQuick] = useState(true);
  const [learnToo, setLearnToo] = useState<boolean | null>(null);
  const [retrain, setRetrain] = useState(false);
  const [offline, setOffline] = useState(false);
  const [noLlm, setNoLlm] = useState(false);
  const [auto, setAuto] = useState(false);
  const [ao, setAo] = useState({ target: 60, max: 100, sectors: 10, min_listed_years: 10 });
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { if (prefs.data && from == null) { setFrom(prefs.data.values.start_year); setTo(prefs.data.values.end_year); } }, [prefs.data, from]);

  const covered = companies.data?.length ?? 0;
  const lists = (lib.data?.lists ?? []).filter((l) => l.count > 0);
  const chosenList = lists.find((l) => l.id === target) ?? null;
  const ceiling = prefs.data?.latest_fy ?? new Date().getFullYear();
  const active = status.data?.active_job;
  const selected = params.get("job") ?? active?.id ?? jobs.data?.[0]?.id ?? null;
  const p = prefs.data?.values;
  const span = from && to ? Math.abs(to - from) + 1 : 0;
  const learnCompanies = learning.data?.companies;
  const useLearn = learnToo ?? learning.data?.settings.use_in_runs ?? true;
  const years = kind !== "research";
  const warn: string[] = [];
  if (years && from && to && Math.max(from, to) > ceiling) warn.push(`FY${Math.max(from, to)} has not ended — it will be trimmed to FY${ceiling}.`);
  if (years && span && span < 3) warn.push("Fewer than 3 years leaves the AI models little to learn from.");

  const count = kind === "learn" ? learnCompanies ?? 0 : chosenList ? chosenList.count : covered;
  const what = kind === "research" ? (quick ? "Quick sweep" : "Full research") : KINDS.find((k) => k.id === kind)!.t;
  const extras = [kind === "valuation" && auto, kind === "research" && noLlm, kind !== "learn" && offline].filter(Boolean).length;

  const launch = () => {
    setErr(null);
    const on = kind === "learn" || offline || !chosenList ? {} : { watchlist: chosenList.id };
    const options: Record<string, unknown> = kind === "research" ? { quick, offline, no_llm: noLlm, ...on }
      : kind === "learn" ? { start_year: from, end_year: to, retrain }
      : { offline, start_year: from, end_year: to, ...on, ...(kind === "valuation" ? (auto ? { auto_train: ao } : { learning: useLearn }) : {}) };
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

  return (
    <div className="page">
      <PageHeader crumbs={[{ label: "Operations" }]} title="Operations" sub="Start a job and follow it live. Each job runs on its own — closing the browser does not stop it." />
      <Panel title="New job" className="nj">
        <div className="jobtype">
          {KINDS.map((k) => <button key={k.id} className={`jt ${kind === k.id ? "on" : ""}`} onClick={() => setKind(k.id)} aria-pressed={kind === k.id}><b><Icon name={k.icon} className="sm" />{k.t}</b><span>{k.d}</span></button>)}
        </div>
        <div className="nj-row">
          <div className="fld nj-co"><span>Companies</span>
            {kind === "learn" ? <span className="nj-fixed small">Every company the models learn from · {learnCompanies ?? "…"}</span> : (
              <Select value={chosenList ? chosenList.id : ALL} onChange={setTarget} style={{ width: "100%" }} ariaLabel="Companies"
                options={[{ value: ALL, label: "Every covered company", hint: covered, icon: "table" }, ...lists.map((l) => ({ value: l.id, label: l.name, hint: l.count, icon: "eye", group: "A watchlist" }))]} />
            )}
          </div>
          {kind === "research" && (
            <div className="fld"><span>Depth</span>
              <div className="seg"><button className={quick ? "on" : ""} onClick={() => setQuick(true)}><Icon name="zap" className="xs" />Quick sweep</button><button className={!quick ? "on" : ""} onClick={() => setQuick(false)}><Icon name="rocket" className="xs" />Full · 23 agents</button></div>
            </div>
          )}
          {years && (
            <div className="fld"><span>Financial years</span>
              <div className="row" style={{ gap: 6 }}>
                <input className="inp num nj-y" inputMode="numeric" aria-label="From FY" value={from ?? ""} onChange={(e) => setFrom(Number(e.target.value.replace(/\D/g, "").slice(0, 4)) || null)} />
                <span className="faint">to</span>
                <input className="inp num nj-y" inputMode="numeric" aria-label="To FY" value={to ?? ""} onChange={(e) => setTo(Number(e.target.value.replace(/\D/g, "").slice(0, 4)) || null)} />
              </div>
            </div>
          )}
          {kind === "valuation" && !auto && <Toggle checked={useLearn} onChange={setLearnToo} label={`Learn from ${learnCompanies ?? "…"} training companies`} />}
          {kind === "learn" && <Toggle checked={retrain} onChange={setRetrain} label="Retrain the models afterwards" />}
          <span className="spacer" />
          {kind !== "learn" && (
            <Popover className="pop nj-adv" trigger={(o, toggle) => <button className={`btn sec ${o ? "on" : ""}`} onClick={toggle} title="Advanced options"><Icon name="settings" className="sm" />Advanced{extras ? <span className="tag info xs">{extras}</span> : null}</button>}>
              {() => (
                <div className="col" style={{ gap: 10 }}>
                  {kind === "valuation" && <Toggle checked={auto} onChange={setAuto} label="Auto-train: add market companies until the Ensemble is confident" />}
                  {kind === "valuation" && auto && (
                    <div className="row wrap" style={{ gap: 10 }}>
                      {([["target", "Target confidence", 5, 95], ["max", "Most companies", 5, 1000], ["sectors", "Top sectors", 1, 25], ["min_listed_years", "Listed ≥ years", 1, 30]] as const).map(([k, l, lo, hi]) => (
                        <label key={k} className="fld" style={{ width: 110 }}><span>{l}</span><input className="inp sm num" type="number" min={lo} max={hi} value={ao[k]} onChange={(e) => setAo({ ...ao, [k]: Math.max(lo, Math.min(hi, Number(e.target.value) || lo)) })} /></label>
                      ))}
                    </div>
                  )}
                  {kind === "research" && <Toggle checked={noLlm} onChange={setNoLlm} label="Rule-based only (no AI calls)" />}
                  <Toggle checked={offline} onChange={setOffline} label="Offline test data (no internet; ignores the companies)" />
                  <span className="xs faint">Defaults for every run (years, data checks, exchange) are in <Link to="/configuration?section=run">Configuration → Runs</Link>.</span>
                </div>
              )}
            </Popover>
          )}
          <button className="btn nj-go" onClick={launch} disabled={!!active || start.isPending}>
            <Icon name={start.isPending ? "loading" : "play"} className={start.isPending ? "spin" : ""} />Start {what.toLowerCase()}{count ? ` · ${count}` : ""}
          </button>
        </div>
        {(warn.length > 0 || err != null || active || kind === "screen") && (
          <div className="nj-msgs">
            {warn.map((w, i) => <span key={i} className="xs warn row"><Icon name="warning" className="xs" />{w}</span>)}
            {kind === "screen" && <span className="xs faint">Settings in use: {p ? (p.screening === "off" ? "no data gate" : `${p.min_complete_fy}+ complete years required`) : "…"}.</span>}
            {active && <span className="xs muted">Waiting for “{jobTitle(active.kind, active.opts)}” to finish.</span>}
            {err != null && <ErrorNote error={err} />}
          </div>
        )}
      </Panel>
      <Panel title="Job detail" meta={selected ? `#${selected}` : undefined}>
        <RunMonitor jobId={selected} />
      </Panel>
      <Panel title="Recent jobs" meta={`${jobs.data?.length ?? 0} jobs · click one to follow it above`} flush>
        <DataGrid rows={jobs.data ?? []} columns={cols} rowKey={(j) => j.id} state={gstate} selected={selected} onSelect={(k) => setParams({ job: k })} empty="No jobs yet." maxHeight="360px" />
      </Panel>
    </div>
  );
}
