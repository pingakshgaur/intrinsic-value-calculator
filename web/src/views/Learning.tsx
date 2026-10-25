import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../lib/api";
import { useStartJob, useStatus } from "../lib/hooks";
import { LearningRun, LearningStatus, useLearning } from "../lib/live";
import { ago, isNum, pctUnits, when } from "../lib/format";
import { HM_COLOR } from "../lib/labels";
import { Icon, Meter, PageHeader, Panel, QueryView, Tip, Toggle } from "../components/ui";
import { jobTitle } from "../components/Shell";
import { useApp } from "../components/workbenchContext";

const LIST_NAME: Record<string, string> = { "training list": "Training list", "auto-train": "Auto-train picks", watchlist: "Watchlist" };

export function Learning() {
  const q = useLearning();
  return (
    <div className="page">
      <PageHeader crumbs={[{ label: "Models & data" }, { label: "Learning" }]} title="Learning data"
        sub="Every company the app knows about — not just the ones you value — becomes training data for the AI/ML models, and through them the HYBRID MODEL's learning lens and calibration." />
      <QueryView q={q} rows={10}>{(d) => <Body d={d} />}</QueryView>
    </div>
  );
}

function Body({ d }: { d: LearningStatus }) {
  const start = useStartJob();
  const status = useStatus();
  const qc = useQueryClient();
  const app = useApp();
  const busy = !!status.data?.active_job;
  const c = d.current;
  const s = d.settings;
  const total = d.cache.fresh + d.cache.stale + d.cache.missing;
  const set = (patch: Record<string, unknown>) =>
    api.put("/api/learning/settings", patch).then(() => qc.invalidateQueries({ queryKey: ["learning"] }))
      .catch((e) => app.toast(e instanceof Error ? e.message : String(e), "error"));
  const run = (kind: string, options: Record<string, unknown>) => start.mutate({ kind, options }, {
    onSuccess: (j) => app.toast(`${jobTitle(j.kind, j.opts)} started — follow it in Operations`), onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
  });
  const first = d.history.find((h) => isNum(h.hm_confidence));
  const last = [...d.history].reverse().find((h) => isNum(h.hm_confidence));
  const delta = first && last && first !== last ? (last.hm_confidence ?? 0) - (first.hm_confidence ?? 0) : null;

  const band = [
    { k: "Learning companies", v: d.companies.toLocaleString("en-IN"), s: `+ ${d.valued} you value · ${d.sectors} sectors` },
    { k: `Cached for FY${d.window[0]}–${d.window[1]}`, v: `${d.cache.fresh} / ${total}`, s: `${d.cache.missing} not fetched · ${d.cache.stale} older than ${d.cache.cache_days} days` },
    { k: "Training rows (last report)", v: isNum(c.labelled_rows) ? c.labelled_rows.toLocaleString("en-IN") : "—", s: isNum(c.training_companies) ? `from ${c.training_companies} companies` : "run a valuation report" },
    { k: "HYBRID MODEL confidence", v: isNum(c.hm_confidence) ? c.hm_confidence.toFixed(1) : "—", s: delta != null ? `${delta >= 0 ? "+" : ""}${delta.toFixed(1)} since the first recorded run` : `mean, FY${c.hm_fy ?? "—"}` },
    { k: "HYBRID MODEL median error", v: isNum(c.hm_medape) ? pctUnits(c.hm_medape) : "—", s: isNum(c.hm_hit20) ? `${pctUnits(c.hm_hit20)} within ±20%` : "" },
    { k: "ML direction", v: isNum(c.ml_direction) ? pctUnits(c.ml_direction) : "—", s: "up/down called right, forward folds" },
  ];

  return (
    <>
      <div className="band">{band.map((b) => <div key={b.k}><div className="k">{b.k}</div><div className="v">{b.v}</div><div className="s">{b.s}</div></div>)}</div>
      <div className="grid c-12">
        <Panel title="Feed and retrain">
          <div className="col" style={{ gap: 12 }}>
            <Toggle checked={s.use_in_runs} onChange={(v) => set({ use_in_runs: v })} label={`Train on all ${d.companies} learning companies in every valuation run`} />
            <Toggle checked={s.auto_feed} onChange={(v) => set({ auto_feed: v })} label="Fetch new and stale companies every day after the close" />
            {s.auto_feed && (
              <div className="row" style={{ paddingLeft: 40, gap: 10 }}>
                <label className="fld" style={{ width: 110 }}><span>After (IST)</span><input className="inp sm mono" defaultValue={s.feed_after} onBlur={(e) => e.target.value !== s.feed_after && set({ feed_after: e.target.value })} /></label>
                <Toggle checked={s.auto_retrain} onChange={(v) => set({ auto_retrain: v })} label="then retrain (a full valuation run)" />
              </div>
            )}
            <span className="xs faint">Last automatic feed: {s.last_auto ?? "never"}. It only starts when no other job is running and the server is on.</span>
            <div className="row" style={{ flexWrap: "wrap" }}>
              <button className="btn sec" disabled={busy || start.isPending} onClick={() => run("learn", {})}><Icon name="cloud-download" className="sm" />Fetch now</button>
              <button className="btn sec" disabled={busy || start.isPending} onClick={() => run("learn", { retrain: true })}><Icon name="sync" className="sm" />Fetch and retrain</button>
              <button className="btn" disabled={busy || start.isPending} onClick={() => run("valuation", { learning: true, start_year: d.window[0], end_year: d.window[1] })}><Icon name="play" className="sm" />Retrain now</button>
            </div>
            {busy && <span className="xs muted">“{jobTitle(status.data!.active_job!.kind, status.data!.active_job!.opts)}” is running — these start when it ends.</span>}
          </div>
        </Panel>
        <Panel title="What the learning set holds">
          <div className="col" style={{ gap: 10 }}>
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              {Object.entries(d.by_list).map(([k, v]) => <span key={k} className="tag">{LIST_NAME[k] ?? k} <b className="mono">{v}</b></span>)}
            </div>
            <div className="row small"><Meter value={total ? (100 * d.cache.fresh) / total : 0} width={180} /><span className="muted">{total ? Math.round((100 * d.cache.fresh) / total) : 0}% ready to train without downloading</span></div>
            <div className="col" style={{ gap: 3 }}>
              {d.by_sector.map(([sec, n]) => (
                <div key={sec} className="row small" style={{ gap: 8 }}>
                  <span className="muted ellipsis" style={{ width: 200 }}>{sec}</span>
                  <div className="grow" style={{ height: 6, background: "var(--raise)", borderRadius: 3 }}><div style={{ width: `${(100 * n) / d.by_sector[0][1]}%`, height: "100%", background: "var(--c-blue)", borderRadius: 3, opacity: 0.7 }} /></div>
                  <span className="mono xs" style={{ width: 30, textAlign: "right" }}>{n}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>
      <History runs={d.history} />
      <div className="note inf">
        <Icon name="info" />
        <div className="small" style={{ lineHeight: 1.6 }}>
          <b>What feeds the models, and what does not.</b> The ML models learn from one row per company per financial year: that year's accounts, and how the price moved over the next year.
          A live price on its own is not a training example, so the minute-by-minute prices the tracker stores are used to <i>value at today's price</i>, not to train.
          What grows the training set is more companies: each one adds its years of accounts. Confidence rises only if that extra data makes the six lenses agree and calibrate better; the chart above records every run so you can see whether it did rather than take it on trust.
          Yahoo Finance serves about four years of accounts per company, so most companies add 2–3 labelled rows.
        </div>
      </div>
    </>
  );
}

function History({ runs }: { runs: LearningRun[] }) {
  const data = useMemo(() => runs.map((r, i) => ({
    i: i + 1, when: when(r.t), rows: r.labelled_rows ?? null, confidence: r.hm_confidence ?? null, error: r.hm_medape ?? null,
    learning: r.learning, auto: r.auto_train, companies: r.training_companies ?? null,
  })), [runs]);
  return (
    <Panel title="Does more data help? Every valuation run, recorded" meta={runs.length ? `${runs.length} run${runs.length === 1 ? "" : "s"} · last ${ago(runs[runs.length - 1].t)}` : "recorded from the next valuation run"}>
      {runs.length === 0 ? (
        <div className="empty" style={{ padding: 30 }}><Icon name="graph-line" /><span className="small">After each valuation run the page records the training rows, the HYBRID MODEL's confidence and its error here.</span></div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="2 4" />
              <XAxis dataKey="i" tickLine={false} axisLine={{ stroke: "var(--line)" }} tickFormatter={(v) => `#${v}`} />
              <YAxis yAxisId="rows" tickLine={false} axisLine={false} width={56} />
              <YAxis yAxisId="pct" orientation="right" unit="" tickLine={false} axisLine={false} width={40} />
              <Tooltip content={<Tip title={(l) => `Run #${l} · ${data[Number(l) - 1]?.when ?? ""}`} fmt={(v, n) => (n === "Training rows" ? Number(v).toLocaleString("en-IN") : isNum(v) ? v.toFixed(1) : "—")} />} />
              <Legend iconType="plainline" />
              <Bar yAxisId="rows" dataKey="rows" name="Training rows" fill="#57a3f8" fillOpacity={0.35} />
              <Line yAxisId="pct" dataKey="confidence" name="HYBRID MODEL confidence" stroke={HM_COLOR} strokeWidth={2.5} dot connectNulls />
              <Line yAxisId="pct" dataKey="error" name="Median error %" stroke="#ef8773" strokeWidth={1.5} dot connectNulls />
            </ComposedChart>
          </ResponsiveContainer>
          <table className="dg" style={{ marginTop: 8 }}>
            <thead><tr><th>Run</th><th>When</th><th>Data</th><th className="r">Companies</th><th className="r">Rows</th><th className="r">Confidence</th><th className="r">Median error</th><th className="r">±20% hits</th></tr></thead>
            <tbody>{[...data].reverse().slice(0, 12).map((r) => {
              const run = runs[r.i - 1];
              return (
                <tr key={r.i}>
                  <td className="mono">#{r.i}</td><td className="muted">{r.when}</td>
                  <td>{r.auto ? <span className="tag">auto-train</span> : r.learning ? <span className="tag hm">learning data</span> : <span className="tag">your companies only</span>}</td>
                  <td className="r mono">{r.companies ?? "—"}</td><td className="r mono">{r.rows?.toLocaleString("en-IN") ?? "—"}</td>
                  <td className="r mono" style={{ color: HM_COLOR }}>{isNum(r.confidence) ? r.confidence.toFixed(1) : "—"}</td>
                  <td className="r mono">{pctUnits(r.error)}</td><td className="r mono">{pctUnits(run.hm_hit20)}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </>
      )}
    </Panel>
  );
}
