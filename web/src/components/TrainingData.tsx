import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { useStartJob, useStatus } from "../lib/hooks";
import { LearningStatus, useLearning } from "../lib/live";
import { ago, isNum, pctUnits, when } from "../lib/format";
import { HM_COLOR } from "../lib/labels";
import { Icon, Meter, Panel, QueryView, Tip, Toggle } from "./ui";
import { jobTitle } from "./Shell";
import { useApp } from "./workbenchContext";

/** What the AI models learn from, whether it is up to date, and whether more of it is helping - in plain words. */
export function TrainingData() {
  const q = useLearning();
  return <QueryView q={q} rows={8}>{(d) => <Body d={d} />}</QueryView>;
}

function Body({ d }: { d: LearningStatus }) {
  const start = useStartJob();
  const status = useStatus();
  const qc = useQueryClient();
  const app = useApp();
  const busy = !!status.data?.active_job || start.isPending;
  const s = d.settings;
  const total = d.cache.fresh + d.cache.stale + d.cache.missing;
  const ready = total ? Math.round((100 * d.cache.fresh) / total) : 0;
  const set = (patch: Record<string, unknown>) =>
    api.put("/api/learning/settings", patch).then(() => qc.invalidateQueries({ queryKey: ["learning"] }))
      .catch((e) => app.toast(e instanceof Error ? e.message : String(e), "error"));
  const refresh = () => start.mutate({ kind: "learn", options: { retrain: s.auto_retrain } }, {
    onSuccess: (j) => { app.toast(`${jobTitle(j.kind, j.opts)} started`, "ok"); app.showJob(j.id); },
    onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
  });
  // the trend in the HYBRID MODEL's typical error across runs: falling is better
  const errs = d.history.map((h) => h.hm_medape).filter(isNum) as number[];
  const trend = errs.length > 1 ? errs[errs.length - 1] - errs[0] : null;
  const verdict = trend == null ? { t: "Not enough runs yet", c: "", s: "each valuation run adds a point" }
    : trend < -0.5 ? { t: "Getting more accurate", c: "up", s: `typical error down ${pctUnits(-trend)} since the first run` }
    : trend > 0.5 ? { t: "Less accurate lately", c: "down", s: `typical error up ${pctUnits(trend)} since the first run` }
    : { t: "Holding steady", c: "", s: "typical error about the same as the first run" };

  return (
    <>
      <div className="band">
        <div><div className="k">Companies the models learn from</div><div className="v">{d.companies.toLocaleString("en-IN")}</div><div className="s">across {d.sectors} sectors, plus the {d.valued} you value</div></div>
        <div><div className="k">Ready to use</div><div className="v">{ready}%</div><div className="s">{d.cache.missing + d.cache.stale ? `${d.cache.missing + d.cache.stale} need a refresh` : "all up to date"}</div></div>
        <div><div className="k">Is more data helping?</div><div className={`v ${verdict.c}`} style={{ fontSize: 17 }}>{verdict.t}</div><div className="s">{verdict.s}</div></div>
      </div>
      <div className="grid c-12">
        <Panel title="Keep it up to date">
          <div className="col" style={{ gap: 12 }}>
            <Toggle checked={s.use_in_runs} onChange={(v) => set({ use_in_runs: v })} label="Learn from all of these companies in every valuation run" />
            <Toggle checked={s.auto_feed} onChange={(v) => set({ auto_feed: v })} label="Refresh their data every evening after the market closes" />
            <Toggle checked={s.auto_retrain} onChange={(v) => set({ auto_retrain: v })} label="Retrain the models after each refresh" />
            {s.auto_feed && (
              <label className="fld row" style={{ gap: 10 }}><span style={{ margin: 0 }}>Refresh after (IST)</span>
                <input className="inp sm mono" style={{ width: 80 }} defaultValue={s.feed_after} onBlur={(e) => e.target.value !== s.feed_after && set({ feed_after: e.target.value })} /></label>
            )}
            <div className="row">
              <button className="btn" disabled={busy} onClick={refresh}><Icon name={start.isPending ? "loading" : "sync"} className={`sm ${start.isPending ? "spin" : ""}`} />{s.auto_retrain ? "Refresh and retrain now" : "Refresh now"}</button>
              <span className="xs faint">Last automatic refresh: {s.last_auto ?? "never"}</span>
            </div>
          </div>
        </Panel>
        <Panel title="What the models have seen" meta={`${ready}% ready`}>
          <div className="col" style={{ gap: 4 }}>
            <div className="row small" style={{ marginBottom: 6 }}><Meter value={ready} width={180} /><span className="muted">{d.cache.fresh} of {total} companies have fresh accounts</span></div>
            {d.by_sector.slice(0, 12).map(([sec, n]) => (
              <div key={sec} className="row small" style={{ gap: 8 }}>
                <span className="muted ellipsis" style={{ width: 200 }}>{sec}</span>
                <div className="grow" style={{ height: 6, background: "var(--raise)", borderRadius: 3 }}><div style={{ width: `${(100 * n) / d.by_sector[0][1]}%`, height: "100%", background: "var(--c-blue)", borderRadius: 3, opacity: 0.7 }} /></div>
                <span className="mono xs" style={{ width: 30, textAlign: "right" }}>{n}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
      <Trend d={d} />
    </>
  );
}

function Trend({ d }: { d: LearningStatus }) {
  const data = useMemo(() => d.history.map((r) => ({ when: when(r.t), companies: r.training_companies ?? null, error: r.hm_medape ?? null })), [d.history]);
  return (
    <Panel title="Accuracy over time" meta={d.history.length ? `${d.history.length} runs · last ${ago(d.history[d.history.length - 1].t)}` : undefined}>
      {data.length < 2 ? (
        <div className="empty" style={{ padding: 30 }}><Icon name="graph-line" /><span className="small">After two valuation runs this shows whether learning from more companies made the HYBRID MODEL more accurate.</span></div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="2 4" />
              <XAxis dataKey="when" tickLine={false} axisLine={{ stroke: "var(--line)" }} minTickGap={40} />
              <YAxis yAxisId="n" tickLine={false} axisLine={false} width={44} />
              <YAxis yAxisId="e" orientation="right" unit="%" tickLine={false} axisLine={false} width={44} />
              <Tooltip content={<Tip fmt={(v, n) => (n === "Companies learned from" ? String(v) : pctUnits(v))} />} />
              <Legend iconType="plainline" />
              <Bar yAxisId="n" dataKey="companies" name="Companies learned from" fill="#57a3f8" fillOpacity={0.3} />
              <Line yAxisId="e" dataKey="error" name="Typical error (lower is better)" stroke={HM_COLOR} strokeWidth={2.5} dot connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="xs faint" style={{ marginTop: 6 }}>Typical error: how far the HYBRID MODEL's value sat from the price a month after each year closed, for the middle company.</div>
        </>
      )}
    </Panel>
  );
}
