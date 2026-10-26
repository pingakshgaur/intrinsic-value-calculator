import { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { AgentStatus, colorOf, KIND_META, Msg, Progress, Roster, RunInfo, timeOf } from "../lib/agents";
import { routes, TEAM_ORDER } from "../lib/agentGraph";
import { ago } from "../lib/format";
import { AgentAvatar } from "./AgentAvatar";
import { AgentProfile } from "./AgentProfile";
import { Icon } from "./ui";

export type InspectorTab = "activity" | "agent" | "edge";

/** The Agent Network's side panel: the run at a glance, one agent, or one edge's traffic. */
export function NetworkInspector({ roster, tab, setTab, sel, selEdge, status, seen, all, live, playing, run, runId, prog, nodeTitle, onPick, agentTab = "about", edgeView, onClose }: {
  roster: Roster;
  tab: InspectorTab;
  setTab: (t: InspectorTab) => void;
  sel: string | null;
  selEdge: string | null;
  status: Record<string, AgentStatus>;
  /** messages up to now: the live window, or the replay up to its clock */
  seen: Msg[];
  /** every message of the run, for an edge's history */
  all: Msg[];
  live: boolean;
  playing: boolean;
  run: RunInfo | null | undefined;
  runId: number | null;
  prog: Progress | null | undefined;
  nodeTitle: (id: string) => string | undefined;
  onPick: (cs: string) => void;
  agentTab?: "about" | "settings";
  /** shown in the Edge tab instead of the traffic list (e.g. the editor for a link you drew) */
  edgeView?: ReactNode;
  onClose?: () => void;
}) {
  const nav = useNavigate();
  const isAgent = !!sel && roster.agents.some((a) => a.callsign === sel);
  return (
    <aside className="an-side">
      <div className="an-tabs">
        <button className={tab === "activity" ? "on" : ""} onClick={() => setTab("activity")}><Icon name="pulse" className="xs" />Activity</button>
        <button className={tab === "agent" ? "on" : ""} onClick={() => setTab("agent")} disabled={!sel}><Icon name="hubot" className="xs" />Agent</button>
        <button className={tab === "edge" ? "on" : ""} onClick={() => setTab("edge")} disabled={!selEdge}><Icon name="arrow-swap" className="xs" />Edge</button>
        {onClose && <><span className="spacer" /><button className="ibtn sm" onClick={onClose} title="Close the inspector (I)"><Icon name="close" className="xs" /></button></>}
      </div>
      <div className="an-side-b">
        {tab === "agent" && sel && isAgent ? (
          <AgentProfile cs={sel} roster={roster} status={status[sel]} messages={seen} graphLink={false} startTab={agentTab}
            onMessage={(c) => nav(`/agents/chat?c=${encodeURIComponent(c)}`)} onChannel={(c) => nav(`/agents/chat?c=${c}`)} onPick={onPick} />
        ) : tab === "agent" && sel ? (
          <div className="col" style={{ gap: 8 }}><b>{nodeTitle(sel)}</b><span className="small muted">{roster.sources[sel]?.detail ?? "Where the chief's work goes."}</span></div>
        ) : tab === "edge" && selEdge && edgeView ? edgeView : tab === "edge" && selEdge ? (
          <EdgeTraffic edge={selEdge} all={all} live={live} />
        ) : (
          <Activity roster={roster} status={status} seen={seen} live={live} playing={playing} run={run} runId={runId} prog={prog} onPick={onPick} />
        )}
      </div>
    </aside>
  );
}

function EdgeTraffic({ edge, all, live }: { edge: string; all: Msg[]; live: boolean }) {
  const msgs = all.filter((m) => routes(m).some(([a, b]) => `${a}>${b}` === edge)).slice(-60).reverse();
  return (
    <div className="col" style={{ gap: 8 }}>
      <b>{edge.replace(">", " → ")}</b>
      <span className="xs faint">{msgs.length} message{msgs.length === 1 ? "" : "s"} travelled this edge{live ? "" : " in the replay"}</span>
      {msgs.map((m) => (
        <div key={m.id} className="ap-msg"><span className="k" style={{ color: KIND_META[m.kind]?.color }}>{KIND_META[m.kind]?.label}</span><span className="t">{m.text}</span><span className="xs faint">{timeOf(m.ts)}</span></div>
      ))}
    </div>
  );
}

function Activity({ roster, status, seen, live, playing, run, runId, prog, onPick }: {
  roster: Roster; status: Record<string, AgentStatus>; seen: Msg[]; live: boolean; playing: boolean;
  run: RunInfo | null | undefined; runId: number | null; prog: Progress | null | undefined; onPick: (cs: string) => void;
}) {
  const working = Object.entries(status).filter(([, s]) => s.state === "working");
  const chat = seen.filter((m) => m.channel !== "trace");
  const recent = chat.slice(-18).reverse();
  const teamLoad = TEAM_ORDER.concat(["CMD"]).map((t) => ({ t, n: seen.filter((m) => m.sender.startsWith(t)).length }));
  const maxLoad = Math.max(1, ...teamLoad.map((x) => x.n));
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="an-run">
        <div className="row"><b>Run #{run?.id ?? runId ?? "-"}</b><span className="tag xs">{run?.mode ?? ""}</span><span className="spacer" /><span className={`live-dot ${live ? "on" : ""}`}>{live ? "live" : run?.finished ? `finished ${ago(Date.parse(run.finished) / 1000)}` : ""}</span></div>
        {prog && <div className="rr-prog"><div style={{ width: `${(100 * prog.done) / Math.max(1, prog.total)}%` }} /><span>{prog.done}/{prog.total} companies</span></div>}
        <div className="ap-stats">
          <div><b>{prog?.messages ?? 0}</b><span>messages</span></div>
          <div><b>{prog?.fetched ?? 0}</b><span>feeds fetched</span></div>
          <div><b>{prog?.saved ?? 0}</b><span>calls saved by sharing</span></div>
          <div><b>{run?.llm_calls ?? 0}</b><span>LLM calls</span></div>
        </div>
      </div>
      <div>
        <div className="label" style={{ marginBottom: 6 }}>Working now · {working.length}</div>
        {working.length === 0 ? <span className="xs faint">{live ? "Between companies." : playing ? "…" : "Nobody - the run is over. Press play to replay it."}</span> : working.slice(0, 12).map(([cs, s]) => (
          <button key={cs} className="rr-agent" onClick={() => onPick(cs)}>
            <AgentAvatar role={roster.agents.find((a) => a.callsign === cs)?.role ?? "analyst"} color={colorOf(roster, cs)} size={22} status="working" />
            <span className="cs">{cs}</span><span className="grow ellipsis faint">{s.companies?.[0] ?? s.task}</span>
          </button>
        ))}
      </div>
      <div>
        <div className="label" style={{ marginBottom: 6 }}>Traffic by team</div>
        {teamLoad.map(({ t, n }) => (
          <div key={t} className="an-load"><span style={{ color: roster.teams[t]?.color }}>{t}</span><div><i style={{ width: `${(100 * n) / maxLoad}%`, background: roster.teams[t]?.color }} /></div><span className="mono xs">{n}</span></div>
        ))}
      </div>
      <div>
        <div className="label" style={{ marginBottom: 6 }}>Latest traffic</div>
        {recent.length === 0 && <span className="xs faint">Nothing yet.</span>}
        {recent.map((m) => (
          <button key={m.id} className="an-feed" onClick={() => onPick(m.sender)}>
            <i style={{ background: KIND_META[m.kind]?.color }} /><b style={{ color: colorOf(roster, m.sender) }}>{m.sender}</b>{m.to ? <span className="faint">→ {m.to}</span> : <span />}<span className="ellipsis">{m.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
