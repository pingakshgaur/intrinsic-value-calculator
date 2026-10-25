import { useEffect, useMemo, useRef, useState } from "react";
import { api, JobDetail } from "../lib/api";
import { useRefreshResults } from "../lib/hooks";
import { duration } from "../lib/format";
import { ErrorNote, Icon } from "./ui";
import { useApp } from "./workbenchContext";

/** Follow one job's output. Polls only lines it has not seen yet. */
export function useJobStream(jobId: string | null) {
  const [lines, setLines] = useState<string[]>([]);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const refresh = useRefreshResults();

  useEffect(() => {
    setLines([]);
    setJob(null);
    setError(null);
    if (!jobId) return;
    let since = 0;
    let stopped = false;
    let timer: number | undefined;
    let wasRunning = false;
    const tick = async () => {
      try {
        const d = await api.get<JobDetail>(`/api/jobs/${jobId}?since=${since}`);
        if (stopped) return;
        setError(null);
        if (d.new_lines.length) setLines((p) => [...p, ...d.new_lines].slice(-20000));
        since = d.since + d.new_lines.length;
        setJob(d);
        const running = d.status === "running" || d.status === "queued";
        if (running) wasRunning = true;
        if (!running && wasRunning) refresh();
        if (running) timer = window.setTimeout(tick, 800);
      } catch (e) {
        if (stopped) return;
        setError(e);
        timer = window.setTimeout(tick, 3000);
      }
    };
    tick();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  return { lines, job, error };
}

function lineClass(l: string) {
  if (l.startsWith("$ ")) return "cmd";
  if (/FATAL|FAILED|Traceback|Error:|\[exit code [1-9]/.test(l)) return "err";
  if (/WARNING|AUTO-ADJUSTED|problem/.test(l)) return "warn";
  if (/\[exit code 0\]|\bOK\b|\bwrote\b/.test(l)) return "ok";
  if (/^=+$|^ {2}STEP|^\[agents\] run #/.test(l)) return "head";
  return "";
}

export function LogView({ lines, height = 320 }: { lines: string[]; height?: number | string }) {
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => {
    const el = box.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [lines]);
  return (
    <div
      ref={box}
      className="terminal"
      style={{ height }}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
      }}
    >
      {lines.filter((l) => !l.startsWith("[auto-event]")).map((l, i) => (
        <div key={i} className={`term-line ${lineClass(l)}`}>{l || " "}</div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------ interpretation
const VALUATION_STEPS: [string, string][] = [
  ["input", "Reading your company list"],
  ["fetch", "Downloading accounts and share prices"],
  ["gate", "Checking each company has enough data"],
  ["estimate", "Filling small gaps in the accounts"],
  ["ml", "Teaching the AI models"],
  ["ensemble", "Blending the Ensemble"],
  ["hybrid model", "Computing the HYBRID MODEL"],
  ["export", "Writing your spreadsheet and CSV files"],
  ["analyzer", "Drawing the charts"],
];
const AGENT_STEPS: [string, string][] = [
  ["base", "Valuing the companies (base inputs)"],
  ["research", "23 agents researching each company"],
  ["report", "Writing the research report"],
];
const TRANSLATIONS: [RegExp, string][] = [
  [/^\[input\] loaded (\d+)/, "Read {0} companies from your list"],
  [/^\[fetch\] (.+?) \.\.\./, "Downloading data for {0}"],
  [/^\[gate\] AUTO-ADJUSTED/, "Data was thinner than the setting allowed — threshold lowered for this run"],
  [/^\[estimate\]/, "Filling small gaps in the accounts"],
  [/^\[ml\] building/, "Preparing the AI training data"],
  [/^\[ml\] (\d+) rows/, "Training the AI models on {0} company-years"],
  [/^\[ensemble\] valued/, "Ensemble blended"],
  [/^\[hybrid model\] median/, "HYBRID MODEL scored against market prices"],
  [/^\[export\]/, "Writing your report files"],
  [/^\[analyzer\]/, "Drawing the charts"],
  [/^\[agents\] base valuation/, "Valuing the companies before research"],
  [/^\[agents\] researching/, "The research team is at work"],
  [/^\[agents\] (.{6,38}?)\s{2,}(Deep value|Undervalued|Fairly valued|Overvalued|Avoid - red flags|Insufficient evidence)/, "Researched {0}"],
  [/^\[agents\] done/, "Research finished"],
  [/^\[auto\]/, "Auto-training on the live market"],
];

export interface AutoState {
  confidence?: number;
  target?: number;
  learned?: number;
  max?: number;
  current?: string;
  sector?: string;
  paused?: boolean;
  message?: string;
  history: number[];
  done?: boolean;
}

export function interpret(lines: string[], kind: string) {
  const agents = kind === "agents";
  const steps = agents ? AGENT_STEPS : VALUATION_STEPS;
  const reached = new Set<string>();
  let headline = "";
  let total = 0;
  let done = 0;
  const auto: AutoState = { history: [] };
  for (const l of lines) {
    if (l.startsWith("[auto-event] ")) {
      try {
        const e = JSON.parse(l.slice(13));
        if (e.target != null) auto.target = e.target;
        if (e.paused != null) auto.paused = e.paused;
        if (e.kind === "plan") auto.max = e.max;
        if (e.kind === "score") {
          auto.confidence = e.confidence;
          auto.history.push(e.confidence);
        }
        if (e.kind === "fetching") {
          auto.current = e.current;
          auto.sector = e.sector;
        }
        if (e.kind === "learned") {
          auto.learned = e.learned;
          auto.message = `Learned ${e.name} (${e.sector})`;
        }
        if (e.kind === "skipped") auto.message = `Skipped ${e.name}: ${e.why}`;
        if (e.kind === "status" || e.kind === "error") auto.message = e.message;
        if (e.kind === "training") auto.message = "Retraining the models…";
        if (e.kind === "done") {
          auto.done = true;
          auto.message = `Finished learning: ${e.reason}`;
        }
      } catch {
        /* a partial line: ignore */
      }
      continue;
    }
    let m = /loaded (\d+) companies|run #\d+ \(\w+\) - (\d+) companies|for (\d+) companies/.exec(l);
    if (m) total = Number(m[1] ?? m[2] ?? m[3]) || total;
    if (l.startsWith("[fetch] ")) done += 1;
    if (agents && /^\[agents\] .+ price .+ value /.test(l)) done += 1;
    if (agents) {
      if (l.startsWith("[agents] base valuation")) reached.add("base");
      if (l.startsWith("[agents] researching")) { reached.add("base"); reached.add("research"); }
      if (l.startsWith("[agents] done") || l.startsWith("[agents] wrote")) { reached.add("research"); reached.add("report"); }
    } else {
      for (const [k] of steps) if (l.startsWith(`[${k}]`)) reached.add(k);
      if (l.startsWith("[gate]")) reached.add("fetch");
      if (l.startsWith("[export]")) ["input", "fetch", "gate", "estimate", "ml", "ensemble", "hybrid model"].forEach((k) => reached.add(k));
    }
    for (const [re, tpl] of TRANSLATIONS) {
      m = re.exec(l);
      if (m) {
        headline = tpl.replace(/\{(\d)\}/g, (_, i) => (m![Number(i) + 1] ?? "").trim());
        break;
      }
    }
  }
  if (agents) done = Math.min(done, total || done);
  const last = steps.map(([k]) => k).filter((k) => reached.has(k)).pop();
  return { steps, reached, last, headline, total, done: total ? Math.min(done, total) : done, auto };
}

// ------------------------------------------------------------ the monitor
export function RunMonitor({ jobId, compact }: { jobId: string | null; compact?: boolean }) {
  const { lines, job, error } = useJobStream(jobId);
  const [showLog, setShowLog] = useState(!compact);
  const app = useApp();
  const kind = job?.kind ?? "";
  const info = useMemo(() => interpret(lines, kind), [lines, kind]);
  const running = job?.status === "running" || job?.status === "queued";
  const finished = job?.status === "succeeded";

  if (!jobId) return <p className="muted">Nothing has run yet.</p>;
  const pctDone = finished ? 1 : info.total ? info.done / info.total : 0;
  const control = (action: string, value?: number) =>
    api.post(`/api/jobs/${jobId}/control`, { action, value }).catch((e) => app.toast(e instanceof Error ? e.message : String(e), "error"));

  const save = () => {
    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `run_${jobId}.log`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="col" style={{ gap: 14 }}>
      {error != null && <ErrorNote error={error} />}
      <div className="col" style={{ gap: 8 }}>
        <div className="row">
          <span className={`dot ${running ? "busy" : finished ? "ok" : job?.status === "cancelled" ? "" : job ? "bad" : ""}`} />
          <b className="strong grow ellipsis">
            {running
              ? info.headline || "Starting…"
              : finished
                ? kind === "screen" ? "Data check finished — nothing was valued (see Model Performance → Left out)" : "Finished — every view has been refreshed"
                : job?.status === "cancelled" ? "Stopped at your request" : job ? "Failed — the log has the details" : "Loading…"}
          </b>
          {job && <span className="mono faint">{duration((job.finished ?? Date.now() / 1000) - job.started)}</span>}
        </div>
        <div className={`prog ${finished ? "done" : ""}`}><span style={{ width: `${Math.max(running ? 3 : 0, pctDone * 100)}%` }} /></div>
        <div className="row xs faint">
          {info.total > 0 ? <span>{info.done} of {info.total} companies</span> : running ? <span>waiting for the first company</span> : null}
          <span className="spacer" />
          {job && <span className="mono">{job.args.slice(0, 1).join(" ") || kind}</span>}
        </div>
      </div>

      {!compact && (
        <div className="stages">
          {info.steps.map(([k, t]) => {
            const done = info.reached.has(k) && (k !== info.last || finished);
            const now = running && k === info.last;
            return (
              <div key={k} className={`stage ${done ? "done" : ""} ${now ? "now" : ""}`}>
                <div className="rail"><span className="node" /><span className="wire" /></div>
                <div className="tx">{t}</div>
              </div>
            );
          })}
        </div>
      )}

      {(info.auto.confidence != null || info.auto.message || job?.controllable) && kind === "valuation" && (
        <div className="auto">
          <div className="row" style={{ marginBottom: 8 }}>
            <b className="strong">Auto-training</b>
            <span className="spacer" />
            <span className="mono">{info.auto.confidence != null ? info.auto.confidence.toFixed(1) : "—"} <span className="faint">/ {info.auto.target?.toFixed(0) ?? "—"}</span></span>
          </div>
          <div className="tmeter">
            <span style={{ width: `${Math.min(100, info.auto.confidence ?? 0)}%` }} />
            {info.auto.target != null && <i style={{ left: `${info.auto.target}%` }} />}
          </div>
          <div className="muted xs" style={{ marginTop: 8 }}>
            Learned {info.auto.learned ?? 0} of up to {info.auto.max ?? "?"} companies
            {info.auto.current ? ` · now ${info.auto.current}${info.auto.sector ? ` (${info.auto.sector})` : ""}` : ""}
            {info.auto.history.length > 1 ? ` · ${info.auto.history.map((h) => h.toFixed(0)).join(" → ")}` : ""}
          </div>
          {info.auto.message && <div className="small" style={{ marginTop: 4 }}>{info.auto.message}</div>}
          {job?.controllable && (
            <div className="row wrap" style={{ marginTop: 10, gap: 6 }}>
              <button className="btn xs sec" onClick={() => control("pause")}><Icon name={info.auto.paused ? "debug-continue" : "debug-pause"} className="xs" /> {info.auto.paused ? "Resume" : "Pause"}</button>
              <button className="btn xs sec" onClick={() => control("skip")}>Skip company</button>
              <button className="btn xs sec" onClick={() => control("skip_sector")}>Skip sector</button>
              <button className="btn xs sec" onClick={() => control("retrain")}>Retrain now</button>
              <button className="btn xs sec" onClick={() => control("target", -5)}>Target −5</button>
              <button className="btn xs sec" onClick={() => control("target", 5)}>Target +5</button>
              <button className="btn xs" onClick={() => control("stop")}>Finish learning</button>
            </div>
          )}
        </div>
      )}

      <div className="row">
        <button className="btn xs ghost" onClick={() => setShowLog(!showLog)}><Icon name={showLog ? "chevron-down" : "chevron-right"} className="xs" /> Log</button>
        <span className="spacer" />
        {running && <button className="btn xs danger" onClick={() => api.post(`/api/jobs/${jobId}/cancel`)}><Icon name="debug-stop" className="xs" /> Stop</button>}
        <button className="btn xs ghost" onClick={save} disabled={!lines.length}><Icon name="desktop-download" className="xs" /> Save log</button>
      </div>
      {showLog && <LogView lines={lines} height={compact ? 320 : 380} />}
    </div>
  );
}
