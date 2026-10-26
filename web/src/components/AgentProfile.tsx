import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AgentStatus, colorOf, dmId, KIND_META, Msg, roleName, Roster, timeOf, tuned, useProfiles } from "../lib/agents";
import { ago } from "../lib/format";
import { AgentAvatar } from "./AgentAvatar";
import { AgentSettings } from "./AgentSettings";
import { Icon } from "./ui";

const STATE_TEXT: Record<string, string> = { idle: "Idle", working: "Working", done: "Done for this run", error: "Had an error", waiting: "Waiting" };

/** Who an agent is, what it is doing, who it talks to. Used by the chat and the graph. */
export function AgentProfile({ cs, roster, status, messages, onMessage, onChannel, graphLink = true, onPick, startTab = "about" }: {
  cs: string;
  roster: Roster;
  status?: AgentStatus;
  messages: Msg[];
  onMessage?: (channel: string) => void;
  onChannel?: (channel: string) => void;
  graphLink?: boolean;
  onPick?: (cs: string) => void;
  startTab?: "about" | "settings";
}) {
  const [tab, setTab] = useState(startTab);
  useEffect(() => setTab(startTab), [cs, startTab]);
  const prof = useProfiles();
  const a = roster.agents.find((x) => x.callsign === cs);
  if (!a) return null;
  const team = roster.teams[a.team];
  const color = team.color;
  const reads = [...(roster.consumes[cs] ?? [])];
  const readBy = Object.entries(roster.consumes).filter(([, v]) => v.includes(cs)).map(([k]) => k);
  const lead = a.role === "analyst" ? roster.agents.find((x) => x.team === a.team && x.role === "lead") : null;
  const mine = messages.filter((m) => m.sender === cs && m.channel !== "trace").slice(-8).reverse();
  const st = status?.state ?? "idle";
  const chip = (c: string) => (
    <button key={c} className="ap-chip" style={{ ["--tc" as string]: colorOf(roster, c) }} onClick={() => onPick?.(c)} title={roster.agents.find((x) => x.callsign === c)?.title ?? roster.sources[c]?.title}>
      {c}
    </button>
  );
  return (
    <div className="ap">
      <div className="ap-head" style={{ ["--tc" as string]: color }}>
        <AgentAvatar role={a.role} color={color} size={52} status={st} />
        <div style={{ minWidth: 0 }}>
          <div className="ap-cs">{a.callsign}</div>
          <div className="ap-title">{a.title}</div>
          <div className="ap-team"><i style={{ background: color }} />{team.name} · {roleName(a.role)}
            {prof.data?.profiles[cs] && !prof.data.profiles[cs].enabled && <span className="tag down xs">off</span>}
            {tuned(prof.data?.profiles[cs], prof.data?.default).length > 0 && <span className="tag hm xs" title="Settings changed from the defaults">tuned</span>}</div>
        </div>
      </div>
      {a.role !== "system" && (
        <div className="seg ap-tabs">
          <button className={tab === "about" ? "on" : ""} onClick={() => setTab("about")}><Icon name="info" className="xs" />About</button>
          <button className={tab === "settings" ? "on" : ""} onClick={() => setTab("settings")}><Icon name="settings-gear" className="xs" />Settings</button>
        </div>
      )}
      {tab === "settings" && a.role !== "system" ? <AgentSettings cs={cs} roster={roster} /> : <>
      <p className="ap-duty">{a.duty}</p>
      <div className={`ap-state s-${st}`}>
        <span className="dot" /> <b>{STATE_TEXT[st] ?? st}</b>
        {status?.companies?.length ? <span className="ellipsis">· {status.companies.join(", ")}</span> : null}
        <span className="spacer" />
        {status?.since && <span className="xs faint">{ago(status.since)}</span>}
      </div>
      {status && (
        <div className="ap-stats">
          <div><b>{status.done}</b><span>companies done</span></div>
          <div><b>{status.sent}</b><span>messages sent</span></div>
          <div><b>{status.received}</b><span>received</span></div>
          <div><b>{status.llm}</b><span>LLM-assisted</span></div>
          {status.errors > 0 && <div className="down"><b>{status.errors}</b><span>errors</span></div>}
        </div>
      )}
      <div className="ap-sec">
        {lead && <div className="ap-row"><span>Reports to</span><div>{chip(lead.callsign)}</div></div>}
        {a.role === "lead" && <div className="ap-row"><span>Team</span><div>{roster.agents.filter((x) => x.team === a.team && x.role === "analyst").map((x) => chip(x.callsign))}</div></div>}
        {(roster.inputs[cs] ?? []).length > 0 && <div className="ap-row"><span>Data from</span><div>{(roster.inputs[cs] ?? []).map((s) => <span key={s} className="ap-src" title={roster.sources[s]?.detail}>{roster.sources[s]?.title ?? s}</span>)}</div></div>}
        {reads.length > 0 && <div className="ap-row"><span>Reads work of</span><div>{reads.slice(0, 16).map(chip)}{reads.length > 16 && <span className="xs faint">+{reads.length - 16}</span>}</div></div>}
        {readBy.length > 0 && <div className="ap-row"><span>Read by</span><div>{readBy.map(chip)}</div></div>}
      </div>
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        {onMessage && a.role !== "system" && <button className="btn sm" onClick={() => onMessage(dmId(cs, "YOU"))}><Icon name="comment" className="xs" />Message {a.callsign}</button>}
        {onChannel && <button className="btn sm sec" onClick={() => onChannel(team.channel)}><Icon name="comment-discussion" className="xs" />#{team.slug}</button>}
        {graphLink && <Link className="btn sm sec" to={`/agents/network?focus=${encodeURIComponent(cs)}`}><Icon name="type-hierarchy" className="xs" />On the graph</Link>}
      </div>
      {mine.length > 0 && (
        <div className="ap-sec">
          <div className="label">Latest messages</div>
          {mine.map((m) => (
            <div key={m.id} className="ap-msg">
              <span className="k" style={{ color: KIND_META[m.kind]?.color }}>{KIND_META[m.kind]?.label ?? m.kind}</span>
              <span className="t">{m.text}</span>
              <span className="xs faint">{timeOf(m.ts)}</span>
            </div>
          ))}
        </div>
      )}
      </>}
    </div>
  );
}
