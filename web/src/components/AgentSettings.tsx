import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { AgentProfileSettings, LlmMode, Roster, Stance, tuned, useProfiles } from "../lib/agents";
import { Icon, Toggle } from "./ui";
import { useApp } from "./workbenchContext";

const STANCE_HELP: Record<Stance, string> = {
  cautious: "scores x0.75 - slower to call a stock cheap or expensive",
  balanced: "scores as measured",
  bold: "scores x1.25 - stronger opinions from the same evidence",
};
const LLM_HELP: Record<LlmMode, string> = {
  auto: "the model tier each task asks for",
  fast: "always the fast model - cheaper, quicker",
  smart: "always the reasoning model - slower, uses more quota",
  off: "rule-based only - no AI calls, no quota",
};

/** How one agent works: on/off, weight, stance, AI use, confidence floor, standing instructions. */
export function AgentSettings({ cs, roster }: { cs: string; roster: Roster }) {
  const q = useProfiles();
  const qc = useQueryClient();
  const app = useApp();
  const a = roster.agents.find((x) => x.callsign === cs);
  const saved = q.data?.profiles[cs];
  const [p, setP] = useState<AgentProfileSettings | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (saved) setP(saved); }, [cs, saved]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!a || a.role === "system") return null;
  if (!p || !saved) return <div className="xs faint">Loading settings…</div>;
  const analyst = a.role === "analyst";
  const dirty = JSON.stringify(p) !== JSON.stringify(saved);
  const changed = tuned(saved, q.data?.default);
  const set = <K extends keyof AgentProfileSettings>(k: K, v: AgentProfileSettings[K]) => setP({ ...p, [k]: v });
  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/api/agents/profiles/${cs}`, p);
      await qc.invalidateQueries({ queryKey: ["agent-profiles"] });
      app.toast(`${cs} settings saved - they apply from the next run`, "ok");
    } catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); } finally { setBusy(false); }
  };
  const reset = async () => {
    setBusy(true);
    try {
      await api.del(`/api/agents/profiles/${cs}`);
      await qc.invalidateQueries({ queryKey: ["agent-profiles"] });
      app.toast(`${cs} is back to its defaults`, "ok");
    } catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); } finally { setBusy(false); }
  };
  return (
    <div className="as">
      {analyst && <Toggle checked={p.enabled} onChange={(v) => set("enabled", v)} label={p.enabled ? "Takes part in research runs" : "Sits out research runs"} />}
      <label className="as-row">
        <span>Weight in the team report <b className="mono">x{p.weight.toFixed(2)}</b></span>
        <input type="range" className="sl" min={0} max={3} step={0.05} value={p.weight} onChange={(e) => set("weight", Number(e.target.value))} disabled={analyst && !p.enabled} />
      </label>
      <div className="as-row">
        <span>Stance</span>
        <div className="seg">{(["cautious", "balanced", "bold"] as Stance[]).map((s) => <button key={s} className={p.stance === s ? "on" : ""} onClick={() => set("stance", s)}>{s}</button>)}</div>
        <small>{STANCE_HELP[p.stance]}</small>
      </div>
      <div className="as-row">
        <span>AI model</span>
        <div className="seg">{(["auto", "fast", "smart", "off"] as LlmMode[]).map((s) => <button key={s} className={p.llm === s ? "on" : ""} onClick={() => set("llm", s)}>{s}</button>)}</div>
        <small>{LLM_HELP[p.llm]}</small>
      </div>
      <label className="as-row">
        <span>Ignore findings below <b className="mono">{Math.round(p.min_confidence * 100)}%</b> confidence</span>
        <input type="range" className="sl" min={0} max={0.9} step={0.05} value={p.min_confidence} onChange={(e) => set("min_confidence", Number(e.target.value))} />
      </label>
      {analyst && <Toggle checked={p.rerun_quick} onChange={(v) => set("rerun_quick", v)} label="Re-run in quick sweeps (instead of re-using its last full-run finding)" />}
      <label className="as-row">
        <span>Standing instructions</span>
        <textarea className="inp" rows={4} maxLength={1500} value={p.instructions} onChange={(e) => set("instructions", e.target.value)}
          placeholder={"e.g. Focus on debt levels and interest cover.\nTreat promoter pledges above 20% as a red flag."} />
        <small>Added to every AI prompt this agent sends, and to its voice in the Research Room. You can also just tell it in chat.</small>
      </label>
      <div className="row" style={{ gap: 6 }}>
        <button className="btn sm" disabled={!dirty || busy} onClick={save}><Icon name={busy ? "loading" : "check"} className={`xs ${busy ? "spin" : ""}`} />Save</button>
        {dirty && <button className="btn sm ghost" onClick={() => setP(saved)}>Discard</button>}
        <span className="spacer" />
        <button className="btn sm ghost" disabled={!changed.length || busy} onClick={reset} title="Back to the defaults"><Icon name="history" className="xs" />Defaults</button>
      </div>
      {changed.length > 0 && <span className="xs faint">Tuned: {changed.join(", ").replace(/_/g, " ")}</span>}
    </div>
  );
}
