import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Icon, Popover, Toggle } from "./ui";
import { useApp } from "./workbenchContext";

interface AutoStart { settings: { enabled: boolean; mode: "quick" | "full"; llm: boolean; skip_recent: number }; state: { last: number | null; reason: string | null } }

/** Auto-start settings and a "start now" button for the research workforce. */
export function WorkforceControl({ active }: { active: boolean }) {
  const q = useQuery({ queryKey: ["autostart"], queryFn: () => api.get<AutoStart>("/api/agents/autostart"), refetchInterval: 15_000 });
  const qc = useQueryClient();
  const app = useApp();
  const s = q.data?.settings;
  const save = (patch: Partial<AutoStart["settings"]>) => api.put("/api/agents/autostart", patch)
    .then(() => qc.invalidateQueries({ queryKey: ["autostart"] })).catch((e) => app.toast(e instanceof Error ? e.message : String(e), "error"));
  const runNow = () => api.post("/api/agents/autostart/run").then(() => { app.toast("Research workforce started", "ok"); qc.invalidateQueries(); })
    .catch((e) => app.toast(e instanceof Error ? e.message : String(e), "error"));
  return (
    <Popover className="pop wf-pop" trigger={(open, toggle) => (
      <button className={`btn sec ${open ? "on" : ""}`} onClick={toggle} title="Research workforce: auto-start and run now">
        <span className={`live-dot ${active ? "on" : ""}`} />Workforce<Icon name="chevron-down" className="xs" />
      </button>
    )}>
      {() => (
        <div className="wf">
          <div className="wf-h"><b>Research workforce</b><span className={`live-dot ${active ? "on" : ""}`}>{active ? "working now" : "idle"}</span></div>
          {!s ? <span className="xs faint">loading…</span> : (
            <>
              <Toggle checked={s.enabled} onChange={(v) => save({ enabled: v })} label="Start working when the web app starts" />
              <div className="wf-row">
                <span>Run</span>
                <div className="seg"><button className={s.mode === "quick" ? "on" : ""} onClick={() => save({ mode: "quick" })}>Quick sweep</button><button className={s.mode === "full" ? "on" : ""} onClick={() => save({ mode: "full" })}>Full research</button></div>
              </div>
              <Toggle checked={s.llm} onChange={(v) => save({ llm: v })} label="Use the AI models (spends free-tier quota)" />
              <label className="wf-row"><span>Skip if a run finished in the last</span>
                <input className="inp sm num" style={{ width: 64 }} type="number" min={0} max={1440} defaultValue={s.skip_recent} onBlur={(e) => save({ skip_recent: Number(e.target.value) })} /> min</label>
              {q.data?.state.reason && <span className="xs faint">At startup: {q.data.state.reason}.</span>}
            </>
          )}
          <button className="btn" onClick={runNow} disabled={active}><Icon name="rocket" className="sm" />{active ? "Working…" : `Start ${s?.mode === "full" ? "full research" : "a quick sweep"} now`}</button>
        </div>
      )}
    </Popover>
  );
}
