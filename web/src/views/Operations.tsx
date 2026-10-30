import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useJobs, usePrefs, useStartJob, useStatus } from "../lib/hooks";
import { useLearning } from "../lib/live";
import { EVERY, REPORT, useTargets } from "../lib/targets";
import { JobSummary } from "../lib/api";
import { ago, duration, when } from "../lib/format";
import { ErrorNote, Icon, PageHeader, Popover, Toggle } from "../components/ui";
import { Column, DataGrid, useGridState } from "../components/DataGrid";
import { RunMonitor } from "../components/JobLog";
import { jobTitle } from "../components/Shell";
import { useApp } from "../components/workbenchContext";
import { Select } from "../components/Select";

type Kind = "valuation" | "research" | "learn" | "screen";
const KINDS: { id: Kind; icon: string; t: string; d: string }[] = [
  { id: "valuation", icon: "graph", t: "Valuation report", d: "Every model, every year, scored against the market — on your companies and the whole learning pool" },
  { id: "research", icon: "rocket", t: "Research", d: "The agents read news, filings and the market for your watchlists" },
  { id: "learn", icon: "cloud-download", t: "Refresh the learning pool", d: "Fetch accounts for every company the models learn from" },
  { id: "screen", icon: "filter", t: "Data check", d: "Who has enough data — values nothing" },
];
const STATUS_DOT: Record<string, string> = { running: "busy", queued: "busy", succeeded: "ok", failed: "bad" };

/**
 * One form to start any job, then the job followed live and the recent jobs
 * below it. Each job is its own process: closing the browser does not stop it.
 */
export function Operations() {
  const [params, setParams] = useSearchParams();
  const prefs = usePrefs();
  const status = useStatus();
  const jobs = useJobs(!!status.data?.active_job);
  const learning = useLearning();
  const start = useStartJob();
  const app = useApp();
  const [kind, setKind] = useState<Kind>("valuation");
  const targets = useTargets(kind === "valuation" || kind === "screen");
  const [target, setTarget] = useState<string>(EVERY);
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

  const chosen = targets.find(target);
  const ceiling = prefs.data?.latest_fy ?? new Date().getFullYear();
  const active = status.data?.active_job;
  const selected = params.get("job") ?? active?.id ?? jobs.data?.[0]?.id ?? null;
  const p = prefs.data?.values;
  const span = from && to ? Math.abs(to - from) + 1 : 0;
  const ld = learning.data;
  const pool = ld?.companies;
  const ready = ld ? Math.round((100 * ld.cache.fresh) / Math.max(1, ld.cache.fresh + ld.cache.stale + ld.cache.missing)) : null;
  const useLearn = learnToo ?? ld?.settings.use_in_runs ?? true;
  const years = kind !== "research";
  const last = (jobs.data ?? []).find((j) => j.status !== "running" && j.status !== "queued");
  const warn: string[] = [];
  if (years && from && to && Math.max(from, to) > ceiling) warn.push(`FY${Math.max(from, to)} has not ended — it will be trimmed to FY${ceiling}.`);
  if (years && span && span < 3) warn.push("Fewer than 3 years leaves the AI models little to learn from.");
  if (kind !== "learn" && !offline && targets.empty) warn.push("No watchlist has companies yet — add some on the Watchlists page.");

  const count = kind === "learn" ? pool ?? 0 : offline ? 0 : chosen.count;
  const what = kind === "research" ? (quick ? "Quick sweep" : "Full research") : KINDS.find((k) => k.id === kind)!.t;
  const extras = [kind === "valuation" && auto, kind === "research" && noLlm, kind !== "learn" && offline].filter(Boolean).length;

  const launch = () => {
    setErr(null);
    const on = kind === "learn" || offline ? {} : chosen.options;
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
  const kindInfo = KINDS.find((k) => k.id === kind)!;

  return (
    <div className="page wo">
      <PageHeader crumbs={[{ label: "Operations" }]} title="Operations"
        sub={<span className="row" style={{ gap: 10, flexWrap: "wrap" }}>
          <span className={`live-dot ${active ? "on" : ""}`}>{active ? `Running: ${jobTitle(active.kind, active.opts)}` : "Idle"}</span>
          <span className="faint">Each job runs on its own — closing the browser does not stop it</span>
        </span>} />

      <section className="wo-figs" aria-label="Operations in figures">
        <Fig k="Watchlists" v={targets.all.filter((t) => t.value !== EVERY && t.value !== REPORT).length} s={`${targets.all[0].count.toLocaleString("en-IN")} companies across them`} />
        <Fig k="Learning pool" v={pool?.toLocaleString("en-IN") ?? "–"} s={ld ? `${ready}% have fresh accounts · ${ld.sectors} sectors` : "loading…"}>
          {ready != null && <div className="wo-bar"><i style={{ width: `${ready}%` }} /></div>}
        </Fig>
        <Fig k="Running now" v={active ? duration(Date.now() / 1000 - active.started) : "–"} s={active ? jobTitle(active.kind, active.opts) : "nothing is running"} />
        <Fig k="Last job" v={last ? <span className={last.status === "failed" ? "down" : last.status === "succeeded" ? "" : "faint"}>{last.status === "succeeded" ? "Done" : last.status === "failed" ? "Failed" : last.status}</span> : "–"}
          s={last ? `${jobTitle(last.kind, last.opts)} · ${ago(last.finished ?? last.started)}` : "no jobs yet"} />
      </section>

      <section className="wo-sec op-new">
        <header className="wo-h"><h2>New job</h2><span className="faint">{kindInfo.d}</span></header>
        <div className="wo-tabs" role="tablist" aria-label="Job type">
          {KINDS.map((k) => (
            <button key={k.id} role="tab" aria-selected={kind === k.id} className={kind === k.id ? "on" : ""} onClick={() => setKind(k.id)}>
              <Icon name={k.icon} className="xs" />{k.t}
            </button>
          ))}
        </div>
        <div className="op-form">
          <div className="fld op-co"><span>Companies</span>
            {kind === "learn" ? <span className="op-fixed">The whole learning pool · {pool?.toLocaleString("en-IN") ?? "…"}</span> : (
              <Select value={chosen.value} onChange={setTarget} style={{ width: "100%" }} ariaLabel="Companies" options={targets.options} disabled={offline} />
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
                <input className="inp num op-y" inputMode="numeric" aria-label="From FY" value={from ?? ""} onChange={(e) => setFrom(Number(e.target.value.replace(/\D/g, "").slice(0, 4)) || null)} />
                <span className="faint">to</span>
                <input className="inp num op-y" inputMode="numeric" aria-label="To FY" value={to ?? ""} onChange={(e) => setTo(Number(e.target.value.replace(/\D/g, "").slice(0, 4)) || null)} />
              </div>
            </div>
          )}
          {kind === "valuation" && !auto && <Toggle checked={useLearn} onChange={setLearnToo} label={`With the learning pool · ${pool?.toLocaleString("en-IN") ?? "…"}`} />}
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
          <button className="btn nj-go" onClick={launch} disabled={!!active || start.isPending || (kind !== "learn" && !offline && !count)}>
            <Icon name={start.isPending ? "loading" : "play"} className={start.isPending ? "spin" : ""} />Start {what.toLowerCase()}{count ? ` · ${count.toLocaleString("en-IN")}` : ""}
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
      </section>

      <section className="wo-sec">
        <header className="wo-h"><h2>Job detail</h2><span className="faint">{selected ? `#${selected}` : "start a job or pick one below"}</span></header>
        <div className="op-detail"><RunMonitor jobId={selected} /></div>
      </section>

      <section className="wo-sec">
        <header className="wo-h"><h2>Recent jobs</h2><span className="faint">{jobs.data?.length ?? 0} jobs · select one to follow it above</span></header>
        <div className="op-jobs">
          <DataGrid rows={jobs.data ?? []} columns={cols} rowKey={(j) => j.id} state={gstate} selected={selected} onSelect={(k) => setParams({ job: k })} empty="No jobs yet." maxHeight="360px" />
        </div>
      </section>
    </div>
  );
}

function Fig({ k, v, s, children }: { k: string; v: React.ReactNode; s: string; children?: React.ReactNode }) {
  return (
    <div className="wo-fig">
      <div className="wo-k ellipsis">{k}</div>
      <div className="wo-v">{v}</div>
      <div className="wo-s ellipsis">{s}</div>
      {children}
    </div>
  );
}
