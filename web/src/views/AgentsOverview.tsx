import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { AgentStatus, colorOf, Msg, Profiles, roleName, Roster, RunInfo, timeOf, tuned, useAgentRuns, useLiveFeed, useProfiles, useRoster, workforceSize } from "../lib/agents";
import { api } from "../lib/api";
import { ago, isNum, isoWhen, pct } from "../lib/format";
import { LABEL_COLOR } from "../lib/labels";
import { AgentAvatar } from "../components/AgentAvatar";
import { AgentProfile } from "../components/AgentProfile";
import { WorkforceControl } from "../components/WorkforceControl";
import { Drawer, Icon, LabelBadge, PageHeader, QueryView } from "../components/ui";
import { ScopeNote } from "../components/ScopePicker";
import { useScope } from "../lib/scope";
import { ResearchLauncher } from "../components/ResearchLauncher";
import { companyPath } from "../lib/company";

const TEAM_ORDER = ["CMD", "NWS", "EQR", "IGR", "MAO", "IRV"];

/** A run's whole output, counted on the server (the live feed only keeps the latest messages). */
interface RunSummary { run: number | null; companies: string[]; verdicts: Msg[]; flags: Msg[]; kinds: Record<string, number> }

/** Where a verdict puts the price against the value. */
const SIDES = [
  { key: "below", name: "Below value", labels: ["Deep value", "Undervalued"], color: LABEL_COLOR["Deep value"] },
  { key: "fair", name: "Near value", labels: ["Fairly valued"], color: LABEL_COLOR["Fairly valued"] },
  { key: "above", name: "Above value", labels: ["Overvalued", "Avoid - red flags"], color: LABEL_COLOR.Overvalued },
] as const;
const sideOf = (m: Msg) => SIDES.find((s) => (s.labels as readonly string[]).includes(String((m.data as Record<string, unknown>).label ?? "")))?.key ?? "other";
type Filter = "all" | "below" | "fair" | "above" | "flags";

/** The research workforce at a glance: what the latest run covered and concluded, the teams, and past runs. */
export function AgentsOverview() {
  const roster = useRoster();
  return (
    <div className="page wo">
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
  const summ = useQuery({
    queryKey: ["agents-summary", run?.id ?? null],
    queryFn: () => api.get<RunSummary>(`/api/agents/summary${run ? `?run=${run.id}` : ""}`),
    enabled: !!run, refetchInterval: active ? 4000 : 30_000,
  });
  const s = summ.data;

  // a watchlist picked in the top bar: every figure counts its companies only
  const inScope = (company?: string | null) => !scope.list || (!!company && scope.has({ company }));
  const companies = (s?.companies ?? []).filter(inScope);
  const verdicts = (s?.verdicts ?? []).filter((m) => inScope(m.company));
  const flags = (s?.flags ?? []).filter((m) => inScope(m.company));
  const covered = scope.list
    ? { done: companies.length, total: scope.list.count }
    : prog && prog.total ? { done: prog.done, total: prog.total } : { done: s?.companies.length ?? run?.companies ?? 0, total: run?.companies ?? 0 };
  const sides = SIDES.map((x) => ({ ...x, n: verdicts.filter((m) => sideOf(m) === x.key).length }));
  const unclear = verdicts.length - sides.reduce((a, x) => a + x.n, 0);
  const flagged = new Set(flags.map((m) => m.company).filter(Boolean)).size;
  const messages = Object.values(s?.kinds ?? {}).reduce((a, b) => a + b, 0) || prog?.messages || 0;

  return (
    <>
      <PageHeader crumbs={[{ label: "Research workforce" }, { label: "Overview" }]} title="Research workforce"
        sub={<span className="row" style={{ gap: 10, flexWrap: "wrap" }}>
          <span className={`live-dot ${active ? "on" : ""}`}>{active ? `Run #${run?.id} in progress · ${busy} of ${size.agents} agents working` : run ? `Idle · run #${run.id} ${run.finished ? `finished ${ago(Date.parse(run.finished) / 1000)}` : "did not finish"}` : "No research run yet"}</span>
          <span className="faint">{size.agents} agents · {size.teams} teams</span>
        </span>}
        actions={<>
          <WorkforceControl active={active} />
          {active ? <Link className="btn" to="/agents/network"><Icon name="type-hierarchy" className="sm" />Watch it live</Link> : <ResearchLauncher />}
        </>} />

      <ScopeNote />

      <section className="wo-figs" aria-label={`Run #${run?.id ?? ""} in figures`}>
        <Figure k={scope.list ? `Researched on ${scope.list.name}` : "Companies researched"}
          v={<>{covered.done}<span className="wo-of">/{covered.total || "–"}</span></>}
          s={scope.list ? (covered.done ? `of the ${scope.list.count} companies on the list` : "this run did not cover the list") : active ? "in this run so far" : `in run #${run?.id ?? "–"}`}>
          <div className="wo-bar"><i style={{ width: `${(100 * covered.done) / Math.max(1, covered.total)}%` }} /></div>
        </Figure>
        <Figure k="Verdicts" v={verdicts.length} s={verdicts.length ? `${sides[0].n} below · ${sides[1].n} near · ${sides[2].n} above value${unclear ? ` · ${unclear} unclear` : ""}` : "none yet"}>
          <div className="wo-split">
            {sides.map((x) => x.n > 0 && <i key={x.key} style={{ flex: x.n, background: x.color }} title={`${x.name}: ${x.n}`} />)}
            {unclear > 0 && <i style={{ flex: unclear, background: "var(--fg-3)" }} title={`Not enough evidence: ${unclear}`} />}
          </div>
        </Figure>
        <Figure k="Red flags" v={flags.length} s={flags.length ? `on ${flagged} ${flagged === 1 ? "company" : "companies"}` : "none raised"} tone={flags.length ? "down" : undefined} />
        <Figure k="Run" v={run ? `#${run.id}` : "–"} s={run ? `${run.mode} · ${isoWhen(run.started)}` : "start one with Research"}>
          {run && <div className="wo-meta"><span>{messages.toLocaleString("en-IN")} messages</span><span>{run.llm_calls} LLM calls</span>{!!prog?.saved && <span>{prog.saved} calls saved</span>}</div>}
        </Figure>
      </section>

      <div className="wo-main">
        <Output verdicts={verdicts} flags={flags} roster={roster} run={run?.id} loading={summ.isLoading} />
        <Runs runs={runs.data ?? []} current={run?.id} onOpen={(id) => nav(`/agents/network?run=${id}`)} />
      </div>

      <section className="wo-sec">
        <header className="wo-h"><h2>Teams</h2><span className="faint">Select an agent for its profile; the gear opens its settings</span></header>
        <div className="wo-teams">
          {TEAM_ORDER.filter((c) => roster.teams[c]).map((code) => (
            <TeamBlock key={code} code={code} roster={roster} status={status} profiles={prof.data} onAgent={(cs, tab) => setOpen({ cs, tab })} />
          ))}
        </div>
      </section>

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

function Figure({ k, v, s, tone, children }: { k: string; v: React.ReactNode; s: string; tone?: "down"; children?: React.ReactNode }) {
  return (
    <div className="wo-fig">
      <div className="wo-k ellipsis">{k}</div>
      <div className={`wo-v ${tone ?? ""}`}>{v}</div>
      <div className="wo-s ellipsis">{s}</div>
      {children}
    </div>
  );
}

function Output({ verdicts, flags, roster, run, loading }: { verdicts: Msg[]; flags: Msg[]; roster: Roster; run?: number; loading: boolean }) {
  const [filter, setFilter] = useState<Filter>("all");
  const rows = useMemo(() => {
    if (filter === "flags") return flags;
    const vs = filter === "all" ? verdicts : verdicts.filter((m) => sideOf(m) === filter);
    return [...vs].sort((a, b) => b.ts - a.ts);
  }, [filter, verdicts, flags]);
  const count = (f: Filter) => (f === "all" ? verdicts.length : f === "flags" ? flags.length : verdicts.filter((m) => sideOf(m) === f).length);
  const tabs: [Filter, string][] = [["all", "All verdicts"], ["below", "Below value"], ["fair", "Near value"], ["above", "Above value"], ["flags", "Red flags"]];
  return (
    <section className="wo-sec wo-out">
      <header className="wo-h">
        <h2>Output</h2><span className="faint">{run ? `run #${run} · the latest verdict on each company` : ""}</span>
      </header>
      <div className="wo-tabs" role="tablist">
        {tabs.map(([f, name]) => (
          <button key={f} role="tab" aria-selected={filter === f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
            {name}<span>{count(f)}</span>
          </button>
        ))}
      </div>
      <div className="wo-list">
        {!rows.length ? (
          <div className="wo-empty">{loading ? "Loading the run's output…" : filter === "flags" ? "No red flags in this run." : "Nothing here yet. Verdicts appear as the run reaches each company."}</div>
        ) : rows.map((m) => {
          const d = m.data as Record<string, unknown>;
          return (
            <Link key={m.id} className="wo-row" to={m.company ? companyPath(m.company) : "/agents/chat"} title={m.text}>
              <span className="wo-co ellipsis">{m.company ?? m.text}</span>
              {m.kind === "verdict" ? (
                <>
                  <LabelBadge label={String(d.label ?? "")} />
                  <b className={`wo-up mono ${isNum(d.upside) ? (d.upside >= 0 ? "up" : "down") : "faint"}`}>{isNum(d.upside) ? pct(d.upside, 0, true) : "–"}</b>
                </>
              ) : (
                <>
                  <span className="wo-flag ellipsis faint">{m.text}</span>
                  <span className="mono xs" style={{ color: colorOf(roster, m.sender) }}>{m.sender}</span>
                </>
              )}
              <span className="wo-t mono">{timeOf(m.ts).slice(0, 5)}</span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function Runs({ runs, current, onOpen }: { runs: RunInfo[]; current?: number; onOpen: (id: number) => void }) {
  return (
    <section className="wo-sec wo-runs">
      <header className="wo-h"><h2>Runs</h2><span className="faint">Select one to replay it</span></header>
      {!runs.length ? <div className="wo-empty">No runs yet.</div> : (
        <div className="wo-list">
          {runs.slice(0, 20).map((r) => (
            <button key={r.id} className={`wo-run ${r.id === current ? "on" : ""}`} onClick={() => onOpen(r.id)} title="Replay this run on the agent network">
              <span className="mono wo-id">#{r.id}</span>
              <span className="wo-rm">
                <span>{r.mode}{!r.finished && <span className="down"> · did not finish</span>}</span>
                <span className="faint">{isoWhen(r.started)}</span>
              </span>
              <span className="wo-rn mono"><b>{r.companies}</b><small>cos</small></span>
              <span className="wo-rn mono"><b>{(r.messages ?? 0).toLocaleString("en-IN")}</b><small>msgs</small></span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function TeamBlock({ code, roster, status, profiles, onAgent }: { code: string; roster: Roster; status: Record<string, AgentStatus>; profiles?: Profiles; onAgent: (cs: string, tab: "about" | "settings") => void }) {
  const t = roster.teams[code];
  const people = roster.agents.filter((a) => a.team === code).sort((a, b) => (a.role === "analyst" ? 1 : 0) - (b.role === "analyst" ? 1 : 0));
  const working = people.filter((a) => status[a.callsign]?.state === "working").length;
  return (
    <div className="wo-team" style={{ ["--tc" as string]: t.color }}>
      <div className="wo-team-h">
        <b className="mono">{code}</b><span className="grow ellipsis">{t.name}</span>
        {working > 0 && <span className="xs up">{working} working</span>}
        <Link className="ibtn sm" to={`/agents/chat?c=${t.channel}`} title={`Open #${t.slug}`}><Icon name="comment-discussion" className="xs" /></Link>
      </div>
      <p className="wo-team-p">{t.purpose}</p>
      {people.map((a) => {
        const st = status[a.callsign];
        const state = st?.state ?? "idle";
        const p = profiles?.profiles[a.callsign];
        const off = !!p && !p.enabled;
        const changed = tuned(p, profiles?.default);
        return (
          <div key={a.callsign} className={`wo-agent ${off ? "off" : ""}`}>
            <button className="wo-agent-b" onClick={() => onAgent(a.callsign, "about")} title={a.duty}>
              <AgentAvatar role={a.role} color={t.color} size={20} status={state} />
              <span className="cs mono">{a.callsign}</span>
              <span className="grow ellipsis faint">{a.role === "analyst" ? a.title.replace(/ Analyst$/, "") : roleName(a.role)}</span>
              {off ? <span className="tag down xs">off</span> : changed.length > 0 && <span className="tag hm xs" title={changed.join(", ")}>tuned</span>}
              <span className={`wo-st s-${state}`}>{state === "working" ? (st?.companies?.[0]?.replace(/ Limited$/i, "") ?? "working") : st?.done ? `${st.done} done` : state}</span>
            </button>
            <button className="ibtn sm" onClick={() => onAgent(a.callsign, "settings")} title={`${a.callsign} settings`} aria-label={`${a.callsign} settings`}><Icon name="settings-gear" className="xs" /></button>
          </div>
        );
      })}
    </div>
  );
}
