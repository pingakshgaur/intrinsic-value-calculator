import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AgentStatus, colorOf, Msg, Profiles, roleName, Roster, timeOf, tuned, useAgentRuns, useLiveFeed, useProfiles, useRoster, workforceSize } from "../lib/agents";
import { ago, isNum, isoWhen, pct } from "../lib/format";
import { AgentAvatar } from "../components/AgentAvatar";
import { AgentProfile } from "../components/AgentProfile";
import { WorkforceControl } from "../components/WorkforceControl";
import { Drawer, Empty, Icon, LabelBadge, PageHeader, Panel, QueryView } from "../components/ui";
import { ScopeNote } from "../components/ScopePicker";
import { useScope } from "../lib/scope";
import { ResearchLauncher } from "../components/ResearchLauncher";
import { companyPath } from "../lib/company";

const TEAM_ORDER = ["CMD", "NWS", "EQR", "IGR", "MAO", "IRV"];

/** The research workforce at a glance: who is working, what the run has produced, and past runs. */
export function AgentsOverview() {
  const roster = useRoster();
  return (
    <div className="page">
      <QueryView q={roster} rows={10}>{(r) => <Overview roster={r} />}</QueryView>
    </div>
  );
}

function Overview({ roster }: { roster: Roster }) {
  const feed = useLiveFeed(null, 1500);
  const runs = useAgentRuns();
  const nav = useNavigate();
  const prof = useProfiles();
  const scope = useScope();
  const [open, setOpen] = useState<{ cs: string; tab: "about" | "settings" } | null>(null);
  const active = !!feed.live?.active;
  const run = feed.live?.run;
  const prog = feed.live?.progress;
  const status = feed.live?.status ?? {};
  const size = workforceSize(roster);
  const busy = Object.values(status).filter((s) => s.state === "working").length;
  const msgs = feed.messages.filter((m) => m.run === run?.id && m.channel !== "trace");
  const verdicts = msgs.filter((m) => m.kind === "verdict" && m.company);
  const flags = msgs.filter((m) => m.kind === "flag");
  // a watchlist in focus: the run's output for its companies only
  const inScope = (m: Msg) => !scope.list || (!!m.company && scope.has({ company: m.company }));
  const myVerdicts = verdicts.filter(inScope), myFlags = flags.filter(inScope);

  return (
    <>
      <PageHeader crumbs={[{ label: "Research workforce" }, { label: "Overview" }]} title="Research workforce"
        sub={<span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <span className={`live-dot ${active ? "on" : ""}`}>{active ? `Run #${run?.id} in progress` : run ? `Idle · last run #${run.id} ${run.finished ? `finished ${ago(Date.parse(run.finished) / 1000)}` : "did not finish"}` : "No research run yet"}</span>
          <span>{size.agents} agents · {size.teams} teams</span>
        </span>}
        actions={<>
          <WorkforceControl active={active} />
          {active ? <Link className="btn" to="/agents/network"><Icon name="type-hierarchy" className="sm" />Watch it live</Link> : <ResearchLauncher />}
        </>} />

      {verdicts.length + flags.length > 0 && <ScopeNote shown={myVerdicts.length} total={verdicts.length} what="verdicts this run" />}
      <div className="band">
        <div>
          <div className="k">Run</div>
          <div className="v">{run ? `#${run.id}` : "-"}</div>
          <div className="s">{run ? `${run.mode} · started ${isoWhen(run.started)}` : "start one with Research"}</div>
        </div>
        <div>
          <div className="k">Companies</div>
          <div className="v">{prog ? `${prog.done}/${prog.total}` : run?.companies ?? "-"}</div>
          {prog ? <div className="ov-bar"><i style={{ width: `${(100 * prog.done) / Math.max(1, prog.total)}%` }} /></div> : <div className="s">researched</div>}
        </div>
        <div><div className="k">Working now</div><div className="v">{busy}</div><div className="s">of {size.agents} agents</div></div>
        <div><div className="k">Messages</div><div className="v">{prog?.messages ?? msgs.length}</div><div className="s">{prog?.fetched ?? 0} feeds fetched</div></div>
        <div><div className="k">Calls saved</div><div className="v">{prog?.saved ?? 0}</div><div className="s">by agents sharing data</div></div>
        <div><div className="k">LLM calls</div><div className="v">{run?.llm_calls ?? 0}</div><div className="s">{verdicts.length} verdicts · {flags.length} red flags</div></div>
      </div>

      <div className="grid c-21">
        <Panel title="Teams" meta="click an agent for its profile and settings">
          <div className="ov-teams">
            {TEAM_ORDER.filter((c) => roster.teams[c]).map((code) => (
              <TeamCard key={code} code={code} roster={roster} status={status} profiles={prof.data} onAgent={(cs, tab) => setOpen({ cs, tab })} />
            ))}
          </div>
        </Panel>
        <div className="col" style={{ gap: 14, minWidth: 0 }}>
          <Panel title="This run's output" meta={run ? `run #${run.id}` : undefined} flush>
            <Highlights verdicts={myVerdicts} flags={myFlags} roster={roster} />
          </Panel>
          <Panel title="Recent runs" flush>
            {(runs.data ?? []).length === 0 ? <Empty icon="history" title="No runs yet" /> : (
              <div className="dg-wrap" style={{ maxHeight: 340 }}>
                <table className="dg dense">
                  <thead><tr><th>Run</th><th>Mode</th><th>Started</th><th className="r">Cos</th><th className="r">Msgs</th><th className="r">LLM</th></tr></thead>
                  <tbody>
                    {(runs.data ?? []).slice(0, 15).map((r) => (
                      <tr key={r.id} className="click" onClick={() => nav(`/agents/network?run=${r.id}`)} title="Replay this run on the graph">
                        <td className="mono">#{r.id}{!r.finished && <span className="xs faint"> · open</span>}</td>
                        <td>{r.mode}</td>
                        <td className="faint">{r.started?.slice(5, 16).replace("T", " ")}</td>
                        <td className="r">{r.companies}</td>
                        <td className="r">{r.messages ?? 0}</td>
                        <td className="r">{r.llm_calls}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>
      </div>
      {open && (
        <Drawer title={`${open.cs} · ${roster.agents.find((a) => a.callsign === open.cs)?.title ?? ""}`} icon="hubot" onClose={() => setOpen(null)}>
          <AgentProfile cs={open.cs} roster={roster} status={status[open.cs]} messages={feed.messages} startTab={open.tab}
            onMessage={(c) => nav(`/agents/chat?c=${encodeURIComponent(c)}`)} onChannel={(c) => nav(`/agents/chat?c=${c}`)}
            onPick={(cs) => setOpen({ cs, tab: "about" })} />
        </Drawer>
      )}
    </>
  );
}

function TeamCard({ code, roster, status, profiles, onAgent }: { code: string; roster: Roster; status: Record<string, AgentStatus>; profiles?: Profiles; onAgent: (cs: string, tab: "about" | "settings") => void }) {
  const t = roster.teams[code];
  const people = roster.agents.filter((a) => a.team === code).sort((a, b) => (a.role === "analyst" ? 1 : 0) - (b.role === "analyst" ? 1 : 0));
  const working = people.filter((a) => status[a.callsign]?.state === "working").length;
  return (
    <div className="ov-team" style={{ ["--tc" as string]: t.color }}>
      <div className="ov-team-h">
        <i className="sw" /><b className="mono">{code}</b><span className="grow ellipsis">{t.name}</span>
        {working > 0 && <span className="xs" style={{ color: "var(--up)" }}>{working} working</span>}
        <Link className="ibtn sm" to={`/agents/chat?c=${t.channel}`} title={`Open #${t.slug}`}><Icon name="comment-discussion" className="xs" /></Link>
      </div>
      <p className="ov-team-p">{t.purpose}</p>
      {people.map((a) => {
        const st = status[a.callsign];
        const state = st?.state ?? "idle";
        const p = profiles?.profiles[a.callsign];
        const off = p && !p.enabled;
        return (
          <div key={a.callsign} className={`ov-agent-row ${off ? "off" : ""}`}>
            <button className="rr-agent ov-agent" onClick={() => onAgent(a.callsign, "about")} title={a.duty}>
              <AgentAvatar role={a.role} color={t.color} size={22} status={state} />
              <span className="cs">{a.callsign}</span>
              <span className="grow ellipsis faint">{a.role === "analyst" ? a.title.replace(/ Analyst$/, "") : roleName(a.role)}</span>
              {off ? <span className="tag down xs">off</span> : tuned(p, profiles?.default).length > 0 && <span className="tag hm xs" title={tuned(p, profiles?.default).join(", ")}>tuned</span>}
              <span className={`ov-st s-${state}`}>{state === "working" ? (st?.companies?.[0]?.replace(/ Limited$/i, "") ?? "working") : st?.done ? `${st.done} done` : state}</span>
            </button>
            <button className="ibtn sm" onClick={() => onAgent(a.callsign, "settings")} title={`${a.callsign} settings`}><Icon name="settings-gear" className="xs" /></button>
          </div>
        );
      })}
    </div>
  );
}

function Highlights({ verdicts, flags, roster }: { verdicts: Msg[]; flags: Msg[]; roster: Roster }) {
  const items = [...verdicts, ...flags].sort((a, b) => b.ts - a.ts).slice(0, 10);
  if (!items.length) return <Empty icon="verified" title="Nothing yet">Verdicts and red flags from the current run show up here.</Empty>;
  return (
    <div className="ov-hl">
      {items.map((m) => {
        const d = m.data as Record<string, unknown>;
        return (
          <Link key={m.id} className="ov-hl-row" to={m.company ? companyPath(m.company) : "/agents/chat"} title={m.text}>
            {m.kind === "verdict" ? <LabelBadge label={String(d.label ?? "")} /> : <span className="tag down xs"><Icon name="warning" className="xs" />flag</span>}
            <span className="grow ellipsis">{m.company ?? m.text}</span>
            {m.kind === "verdict" && isNum(d.upside) && <b className={`mono xs ${d.upside >= 0 ? "up" : "down"}`}>{pct(d.upside, 0, true)}</b>}
            {m.kind === "flag" && <span className="xs" style={{ color: colorOf(roster, m.sender) }}>{m.sender}</span>}
            <span className="xs faint">{timeOf(m.ts).slice(0, 5)}</span>
          </Link>
        );
      })}
    </div>
  );
}
