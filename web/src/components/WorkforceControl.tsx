import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useWatchlists } from "../lib/live";
import { Icon, Popover, Toggle } from "./ui";
import { useApp } from "./workbenchContext";

interface AutoStart { settings: { enabled: boolean; mode: "quick" | "full"; llm: boolean; skip_recent: number; watchlists: string[] }; state: { last: number | null; reason: string | null } }

/** When the research workforce starts by itself. Starting a run by hand is the Research button (ResearchLauncher). */
export function WorkforceControl({ active }: { active: boolean }) {
  const q = useQuery({ queryKey: ["autostart"], queryFn: () => api.get<AutoStart>("/api/agents/autostart"), refetchInterval: 15_000 });
  const qc = useQueryClient();
  const app = useApp();
  const s = q.data?.settings;
  const lists = (useWatchlists().data?.lists ?? []).filter((l) => l.count > 0);
  // no lists picked = every watchlist
  const picked = (s?.watchlists ?? []).filter((id) => lists.some((l) => l.id === id));
  const pick = (id: string) => save({ watchlists: picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id] });
  const save = (patch: Partial<AutoStart["settings"]>) => api.put("/api/agents/autostart", patch)
    .then(() => qc.invalidateQueries({ queryKey: ["autostart"] })).catch((e) => app.toast(e instanceof Error ? e.message : String(e), "error"));
  return (
    <Popover className="pop wf-pop" trigger={(open, toggle) => (
      <button className={`btn sec ${open ? "on" : ""}`} onClick={toggle} title="When the research workforce starts by itself">
        <span className={`live-dot ${active ? "on" : ""}`} />Auto-start{s ? (s.enabled ? " on" : " off") : ""}<Icon name="chevron-down" className="xs" />
      </button>
    )}>
      {() => (
        <div className="wf">
          <div className="wf-h"><b>Auto-start</b><span className={`live-dot ${active ? "on" : ""}`}>{active ? "working now" : "idle"}</span></div>
          {!s ? <span className="xs faint">loading…</span> : (
            <>
              <Toggle checked={s.enabled} onChange={(v) => save({ enabled: v })} label="Start working when the web app starts" />
              <div className="wf-row">
                <span>Run</span>
                <div className="seg"><button className={s.mode === "quick" ? "on" : ""} onClick={() => save({ mode: "quick" })}>Quick sweep</button><button className={s.mode === "full" ? "on" : ""} onClick={() => save({ mode: "full" })}>Full research</button></div>
              </div>
              <div className="wf-lists">
                <span>Research the companies on</span>
                {!lists.length ? <span className="xs faint">No watchlist has companies yet, so auto-start has nothing to research.</span> : (
                  <div className="row wrap" style={{ gap: 6 }}>
                    <button className={`chip ${picked.length ? "" : "on"}`} onClick={() => save({ watchlists: [] })}>Every watchlist</button>
                    {lists.map((l) => (
                      <button key={l.id} className={`chip ${picked.includes(l.id) ? "on" : ""}`} onClick={() => pick(l.id)} title={`${l.count} companies`}>
                        <span className="sw" style={{ background: l.color }} />{l.name}<span className="faint">{l.count}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <Toggle checked={s.llm} onChange={(v) => save({ llm: v })} label="Use the AI models (spends free-tier quota)" />
              <label className="wf-row"><span>Skip if a run finished in the last</span>
                <input className="inp sm num" style={{ width: 64 }} type="number" min={0} max={1440} defaultValue={s.skip_recent} onBlur={(e) => save({ skip_recent: Number(e.target.value) })} /> min</label>
              {q.data?.state.reason && <span className="xs faint">At startup: {q.data.state.reason}.</span>}
            </>
          )}
        </div>
      )}
    </Popover>
  );
}
