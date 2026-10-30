import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import {
  agentOf, colorOf, dmName, isDm, Kind, KIND_META, Msg, Roster, timeOf, useAgentRuns, useChannelStats, useLiveFeed, useRoster, workforceSize,
} from "../lib/agents";
import { ago } from "../lib/format";
import { useScope } from "../lib/scope";
import { chime } from "../lib/notify";
import { AgentAvatar } from "../components/AgentAvatar";
import { AgentProfile } from "../components/AgentProfile";
import { ChatMessage, RichText } from "../components/ChatMessage";
import { ExportButton } from "../components/ExportButton";
import { Empty, Icon, Popover, QueryView } from "../components/ui";
import { useApp } from "../components/workbenchContext";
import { Select } from "../components/Select";

const SHOWN_KINDS: Kind[] = ["task", "finding", "request", "reply", "flag", "review", "summary", "verdict", "system", "user"];
const READ_KEY = "rr.read.v1";
const OPEN_KEY = "rr.teams.open.v1";

function useChannel(run: number | null, channel: string) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [more, setMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const last = useRef(0);
  const live = useRef(false);
  const kick = useRef<() => void>(() => undefined);
  useEffect(() => {
    let stop = false;
    let timer = 0;
    last.current = 0;
    setMsgs([]);
    setMore(true);
    setLoading(true);
    const q = (extra: Record<string, string>) => new URLSearchParams({ channel, ...(run ? { run: String(run) } : {}), trace: channel === "trace" ? "true" : "false", ...extra });
    const poll = async () => {
      try {
        const d = await api.get<{ run: number; messages: Msg[] }>(`/api/agents/messages?${q(last.current ? { after: String(last.current), limit: "500" } : { limit: "300" })}`);
        if (stop) return;
        if (!last.current) setMore(d.messages.length >= 300);
        if (d.messages.length) {
          const later = last.current > 0;
          last.current = d.messages[d.messages.length - 1].id;
          setMsgs((cur) => [...cur, ...d.messages]);
          if (later && d.messages.some((m) => m.to === "YOU" && m.sender !== "YOU")) chime("agent_reply");
        }
        setLoading(false);
      } catch { /* the next poll retries */ }
      if (!stop) timer = window.setTimeout(poll, live.current ? 1500 : 5000);
    };
    kick.current = () => { window.clearTimeout(timer); poll(); };
    poll();
    return () => { stop = true; window.clearTimeout(timer); };
  }, [run, channel]);
  const loadEarlier = useCallback(async () => {
    const first = msgs[0]?.id;
    if (!first) return;
    const d = await api.get<{ messages: Msg[] }>(`/api/agents/messages?${new URLSearchParams({ channel, before: String(first), limit: "300", trace: String(channel === "trace"), ...(run ? { run: String(run) } : {}) })}`);
    setMore(d.messages.length >= 300);
    setMsgs((cur) => [...d.messages, ...cur]);
  }, [msgs, channel, run]);
  return { msgs, more, loading, loadEarlier, setLive: (v: boolean) => { live.current = v; }, refresh: () => kick.current() };
}

export function AgentChat() {
  const roster = useRoster();
  return (
    <div className="page fill rr-page">
      <QueryView q={roster} rows={10}>{(r) => <Room roster={r} />}</QueryView>
    </div>
  );
}

type Side = { type: "channel" } | { type: "agent"; cs: string } | { type: "msg"; m: Msg } | null;

function Room({ roster }: { roster: Roster }) {
  const [params, setParams] = useSearchParams();
  const channel = params.get("c") || "command";
  const runParam = params.get("run");
  const run = runParam ? Number(runParam) : null;
  const set = (patch: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) { if (v == null) p.delete(k); else p.set(k, v); }
    setParams(p, { replace: true });
  };
  const runs = useAgentRuns();
  const feed = useLiveFeed(run, 1500);
  const stats = useChannelStats(run);
  const ch = useChannel(run, channel);
  const app = useApp();
  ch.setLive(!!feed.live?.active);
  const [side, setSide] = useState<Side>(() => (window.innerWidth >= 1500 ? { type: "channel" } : null));
  const scope = useScope();
  // "@list": only messages about the focused watchlist's companies (and general chat)
  const [company, setCompany] = useState<string>(() => (scope.list ? "@list" : ""));
  useEffect(() => { setCompany((c) => (scope.list ? (c === "" ? "@list" : c) : c === "@list" ? "" : c)); }, [scope.list]);
  const [kinds, setKinds] = useState<Set<Kind>>(new Set());
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // agents asked something and not yet answered: shown as "typing" until their reply lands
  const [waiting, setWaiting] = useState<{ cs: string[]; after: number; until: number } | null>(null);
  const [find, setFind] = useState("");
  // agent groups start folded so the channels stay in view; the ones you open are remembered
  const [openTeams, setOpenTeams] = useState<Set<string>>(() => { try { return new Set(JSON.parse(localStorage.getItem(OPEN_KEY) || "[]")); } catch { return new Set(); } });
  const toggleTeam = (code: string) => setOpenTeams((s) => {
    const n = new Set(s);
    if (n.has(code)) n.delete(code); else n.add(code);
    try { localStorage.setItem(OPEN_KEY, JSON.stringify([...n])); } catch { /* private mode */ }
    return n;
  });
  const [read, setRead] = useState<Record<string, number>>(() => { try { return JSON.parse(localStorage.getItem(READ_KEY) || "{}"); } catch { return {}; } });
  const listRef = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const [newBelow, setNewBelow] = useState(0);

  const runId = feed.live?.run?.id ?? run;
  const status = feed.live?.status ?? {};
  const counts = stats.data?.channels ?? {};
  const rk = (c: string) => `${stats.data?.run ?? runId}:${c}`;
  // unread = what arrived since you last looked. A channel seen for the first time starts
  // from what is already there; the open channel is always read. One functional update,
  // keyed by the run the counts belong to, so the two rules never overwrite each other.
  const statRun = stats.data?.run ?? null;
  useEffect(() => {
    if (!statRun) return;
    setRead((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const [c, v] of Object.entries(counts)) {
        const k = `${statRun}:${c}`;
        if (next[k] == null || (c === channel && next[k] !== v.count)) { next[k] = v.count; changed = true; }
      }
      if (!changed) return prev;
      try { localStorage.setItem(READ_KEY, JSON.stringify(next)); } catch { /* private mode */ }
      return next;
    });
  }, [statRun, stats.data, channel]); // eslint-disable-line react-hooks/exhaustive-deps

  const meta = roster.channels.find((c) => c.id === channel);
  const dmPeers = isDm(channel) ? channel.slice(3).split("|") : [];
  const members = meta ? meta.members : dmPeers;
  const shown = useMemo(() => {
    const f = find.trim().toLowerCase();
    const onCo = (m: Msg) => !company || (company === "@list" ? !m.company || scope.has({ company: m.company }) : m.company === company);
    return ch.msgs.filter((m) => onCo(m) && (!kinds.size || kinds.has(m.kind)) && (!f || m.text.toLowerCase().includes(f) || m.sender.toLowerCase().includes(f)));
  }, [ch.msgs, company, kinds, find, scope]);
  const companies = useMemo(() => [...new Set(ch.msgs.map((m) => m.company).filter(Boolean) as string[])].sort(), [ch.msgs]);
  const byMid = useMemo(() => new Map(feed.messages.concat(ch.msgs).map((m) => [m.mid, m])), [feed.messages, ch.msgs]);
  const dms = Object.keys(counts).filter(isDm).sort((a, b) => (counts[b].last ?? 0) - (counts[a].last ?? 0));

  // stay pinned to the newest message unless the reader scrolled up
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    if (atBottom.current) { el.scrollTop = el.scrollHeight; setNewBelow(0); }
    else setNewBelow((n) => n + 1);
  }, [shown.length]);
  useEffect(() => { atBottom.current = true; setNewBelow(0); }, [channel, company, kinds]);
  const onScroll = () => {
    const el = listRef.current!;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    if (atBottom.current) setNewBelow(0);
  };
  const toBottom = () => { const el = listRef.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" }); atBottom.current = true; setNewBelow(0); };

  const lastId = ch.msgs[ch.msgs.length - 1]?.id ?? 0;
  useEffect(() => {
    if (!waiting) return;
    const answered = ch.msgs.some((m) => m.id > waiting.after && waiting.cs.includes(m.sender));
    if (answered || Date.now() > waiting.until) { setWaiting(null); return; }
    const t = window.setTimeout(() => ch.refresh(), 1200);
    return () => window.clearTimeout(t);
  }, [waiting, lastId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setWaiting(null), [channel]);
  const answering = waiting?.cs ?? [];
  const typing = answering.length ? [] : members.filter((cs) => status[cs]?.state === "working").slice(0, 4);
  const send = async () => {
    const t = text.trim();
    if (!t) return;
    try {
      const r = await api.post<{ ok: boolean; pending?: string[] }>("/api/agents/messages", { channel, text: t });
      setText("");
      atBottom.current = true;
      if (run) set({ run: null }); // your message goes into the latest run - show it
      setWaiting({ cs: r.pending ?? ["OPS-00"], after: lastId, until: Date.now() + 120_000 });
      ch.refresh();
    } catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); }
  };
  const reply = (m: Msg) => {
    setText((cur) => `@${m.sender} ${cur.replace(/^@[A-Z]{3}-\d{2}\s*/, "")}`);
    window.setTimeout(() => { const el = inputRef.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }, 0);
  };
  const copy = (m: Msg) => { navigator.clipboard?.writeText(m.text).then(() => app.toast("Copied")).catch(() => app.toast("Copy failed", "error")); };
  const open = (c: string) => { set({ c }); setSide({ type: "channel" }); };
  const exportTable = () => ({
    head: ["Time", "From", "To", "Kind", "Company", "Message"],
    rows: shown.map((m) => [timeOf(m.ts), m.sender, m.to ?? "", KIND_META[m.kind]?.label ?? m.kind, m.company ?? "", m.text]),
    subtitle: `Run #${runId ?? "-"} · ${shown.length} messages`,
  });
  const title = meta ? `#${meta.name}` : isDm(channel) ? dmName(channel) : channel;
  const prog = feed.live?.progress;
  const active = !!feed.live?.active;
  // when the latest run has nothing in this channel yet, offer the one before it
  const prevRun = !run ? (runs.data ?? []).find((r) => r.id !== runId && (r.messages ?? 0) > 0)?.id : undefined;

  return (
    <div className="rr">
      <aside className="rr-side">
        <div className="rr-ws">
          <div className="rr-ws-h">
            <div className="crumbs"><span>Research workforce</span><Icon name="chevron-right" className="xs" /><span>Research Room</span></div>
            <h1>Research Room</h1>
            <div className="rr-ws-s">
              <span className={`live-dot ${active ? "on" : ""}`}>{active ? `Run #${runId} live` : "Idle"}</span>
              <span className="faint">{workforceSize(roster).agents} agents · {workforceSize(roster).teams} teams</span>
            </div>
          </div>
          <Select size="sm" value={run == null ? "" : String(run)} onChange={(v) => set({ run: v || null })} ariaLabel="Which run" style={{ width: "100%" }}
            options={[{ value: "", label: `Latest run${feed.live?.run ? ` (#${feed.live.run.id})` : ""}` },
              ...(runs.data ?? []).map((r) => ({ value: String(r.id), label: `#${r.id} · ${r.mode} · ${r.started?.slice(5, 16).replace("T", " ") ?? ""}`, hint: `${r.messages ?? 0} msgs` }))]} />
          {active && prog && (
            <div className="rr-prog" role="progressbar" aria-label="Run progress" aria-valuemin={0} aria-valuemax={prog.total} aria-valuenow={prog.done}>
              <div className="rr-prog-bar"><i style={{ width: `${(100 * prog.done) / Math.max(1, prog.total)}%` }} /></div>
              <span>{prog.done} of {prog.total} companies · {prog.saved} calls saved</span>
            </div>
          )}
        </div>
        <nav className="rr-list" aria-label="Channels and agents">
          <div className="rr-sec">Channels</div>
          {roster.channels.map((c) => {
            const n = counts[c.id]?.count ?? 0;
            const unread = Math.max(0, n - (read[rk(c.id)] ?? 0));
            const busy = c.members.some((cs) => status[cs]?.state === "working");
            return (
              <button key={c.id} className={`rr-item ${channel === c.id ? "on" : ""} ${unread ? "unread" : ""}`} onClick={() => open(c.id)} style={{ ["--tc" as string]: roster.teams[c.team].color }}
                aria-current={channel === c.id ? "page" : undefined}>
                <span className="hash" aria-hidden="true">#</span><span className="grow ellipsis">{c.name}</span>
                {busy && <span className="typing-dots" title="An agent here is working"><i /><i /><i /><span className="sr-only">, agents working</span></span>}
                {unread > 0 && channel !== c.id ? <span className="badge">{unread > 99 ? "99+" : unread}<span className="sr-only"> unread</span></span> : n > 0 ? <span className="xs faint">{n}<span className="sr-only"> messages</span></span> : null}
              </button>
            );
          })}
          <button className={`rr-item ${channel === "trace" ? "on" : ""}`} onClick={() => open("trace")} style={{ ["--tc" as string]: "#4EC9B0" }} title="Every feed fetch and every reuse between agents"
            aria-current={channel === "trace" ? "page" : undefined}>
            <span className="hash"><Icon name="pulse" className="xs" /></span><span className="grow ellipsis">data-exchange trace</span>
            {(counts.trace?.count ?? 0) > 0 && <span className="xs faint">{counts.trace.count}</span>}
          </button>
          <div className="rr-sec">Direct exchanges <span className="faint">{dms.length}</span></div>
          {dms.length === 0 && <div className="xs faint" style={{ padding: "4px 14px" }}>None in this run yet.</div>}
          {dms.slice(0, 40).map((d) => {
            const [x, y] = d.slice(3).split("|");
            return (
              <button key={d} className={`rr-item dm ${channel === d ? "on" : ""}`} onClick={() => open(d)} aria-current={channel === d ? "page" : undefined}>
                <span className="pair" aria-hidden="true"><i style={{ background: colorOf(roster, x) }} /><i style={{ background: colorOf(roster, y) }} /></span>
                <span className="grow ellipsis">{x === "YOU" || y === "YOU" ? `You ↔ ${x === "YOU" ? y : x}` : `${x} ↔ ${y}`}</span>
                <span className="xs faint">{counts[d].count}</span>
              </button>
            );
          })}
          <div className="rr-sec">Agents</div>
          {Object.entries(roster.teams).map(([code, t]) => {
            const people = roster.agents.filter((a) => a.team === code);
            const shut = !openTeams.has(code);
            const working = people.filter((a) => status[a.callsign]?.state === "working").length;
            return (
              <div key={code}>
                <button className="rr-team" onClick={() => toggleTeam(code)} style={{ ["--tc" as string]: t.color }} aria-expanded={!shut}>
                  <Icon name={shut ? "chevron-right" : "chevron-down"} className="xs" /><i className="sw" aria-hidden="true" /><span className="grow ellipsis">{code} · {t.name}</span>
                  {working > 0 && <span className="xs" style={{ color: "var(--up)" }}>{working} busy</span>}
                </button>
                {!shut && people.map((a) => (
                  <button key={a.callsign} className={`rr-agent ${side?.type === "agent" && side.cs === a.callsign ? "on" : ""}`} onClick={() => setSide({ type: "agent", cs: a.callsign })}>
                    <AgentAvatar role={a.role} color={t.color} size={22} status={status[a.callsign]?.state ?? "idle"} />
                    <span className="cs">{a.callsign}</span><span className="grow ellipsis faint">{a.title.replace(/ Analyst$/, "")}</span>
                  </button>
                ))}
              </div>
            );
          })}
        </nav>
      </aside>

      <section className="rr-main" aria-label={`Channel ${title}`}>
        <header className="rr-h">
          <div className="grow" style={{ minWidth: 0 }}>
            <Select className="rr-chsel" size="sm" value={channel} onChange={(c) => open(c)} ariaLabel="Channel" style={{ width: "100%" }}
              options={[...roster.channels.map((c) => ({ value: c.id, label: `#${c.name}` })), { value: "trace", label: "data-exchange trace" }, ...dms.map((d) => ({ value: d, label: dmName(d), group: "Direct exchanges" }))]} />
            <h2 className="rr-title" style={{ ["--tc" as string]: meta ? roster.teams[meta.team].color : "#9A9B9C" }}>
              {meta ? <span className="hash" aria-hidden="true">#</span> : <Icon name={channel === "trace" ? "pulse" : "comment"} />}<b>{channel === "trace" ? "data-exchange trace" : meta ? meta.name : title}</b>
            </h2>
            <div className="xs faint ellipsis">{meta?.purpose ?? (channel === "trace" ? "Every feed an agent fetched, and every time another agent reused it instead of fetching again." : isDm(channel) ? "A direct exchange between two agents." : "This channel does not exist - pick one on the left.")}</div>
          </div>
          <div className="rr-members" title={members.join(", ")}>
            {members.slice(0, 6).map((cs) => (
              <button key={cs} onClick={() => cs !== "YOU" && setSide({ type: "agent", cs })} aria-label={`${cs}${agentOf(roster, cs) ? `, ${agentOf(roster, cs)!.title}` : ""}: open the profile`} title={cs}>
                <AgentAvatar role={agentOf(roster, cs)?.role ?? "user"} color={colorOf(roster, cs)} size={24} status={status[cs]?.state} />
              </button>
            ))}
            {members.length > 6 && <span className="more">+{members.length - 6}</span>}
          </div>
          <div className="rr-tools">
            <div className="search sm"><Icon name="search" /><input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Search" aria-label="Search messages in this channel" /></div>
            <Select size="sm" value={company} onChange={setCompany} style={{ maxWidth: 170 }} ariaLabel="Company" menuWidth={260}
              options={[{ value: "", label: "All companies" }, ...(scope.list ? [{ value: "@list", label: `On ${scope.list.name}`, icon: "eye" }] : []),
                ...companies.map((c) => ({ value: c, label: c }))]} />
            <Popover trigger={(o, toggle) => <button className={`ibtn ${o || kinds.size ? "on" : ""}`} onClick={toggle} title="Filter by kind" aria-label={kinds.size ? `Filter by kind, ${kinds.size} shown` : "Filter by kind"} aria-expanded={o}><Icon name="filter" /></button>}>
              {() => (
                <>
                  <div className="label" style={{ padding: "6px 8px" }}>Show</div>
                  {SHOWN_KINDS.map((k) => (
                    <label key={k}><input type="checkbox" className="cb" checked={!kinds.size || kinds.has(k)}
                      onChange={() => setKinds((s) => { const all = new Set(SHOWN_KINDS); const n = s.size ? new Set(s) : all; if (n.has(k)) n.delete(k); else n.add(k); return n.size === all.size ? new Set() : n; })} />
                      <Icon name={KIND_META[k].icon} className="xs" style={{ color: KIND_META[k].color }} />{KIND_META[k].label}</label>
                  ))}
                </>
              )}
            </Popover>
            <ExportButton title={`Research Room ${title}`} table={exportTable} />
            <button className={`ibtn ${side ? "on" : ""}`} onClick={() => setSide(side ? null : { type: "channel" })} title="Details" aria-label="Channel details" aria-pressed={!!side}><Icon name="layout-sidebar-right" /></button>
          </div>
        </header>
        {/* a chat log: new messages are read out politely, but not while a run floods the channel */}
        <div className="rr-msgs" ref={listRef} onScroll={onScroll} role="log" aria-label={`Messages in ${title}`} aria-live={active ? "off" : "polite"} tabIndex={0}>
          {ch.more && ch.msgs.length > 0 && <button className="rr-more" onClick={ch.loadEarlier}>Load earlier messages</button>}
          {ch.loading ? <div className="empty" style={{ padding: 40 }}><Icon name="loading" className="spin" /></div>
            : shown.length === 0 ? (ch.msgs.length ? (
              <Empty icon="filter" title="Nothing matches these filters"
                action={<button className="btn sm sec" onClick={() => { setFind(""); setCompany(""); setKinds(new Set()); }}>Clear filters</button>}>
                Clear the search, company or kind filter.
              </Empty>
            ) : (
              <Empty icon="comment-discussion" title={active ? `Run #${runId} has just started` : "No messages here yet"}
                action={prevRun ? <button className="btn sm sec" onClick={() => set({ run: String(prevRun) })}><Icon name="history" className="xs" />Read run #{prevRun}</button> : undefined}>
                {active ? "The agents post here as they finish each company." : "Start a research run - the agents report here as they work."}
              </Empty>
            ))
            : shown.map((m, i) => {
              const p = shown[i - 1];
              const grouped = !!p && p.sender === m.sender && m.ts - p.ts < 120 && p.kind !== "user" && m.kind !== "verdict";
              const newCo = !!m.company && m.kind === "task" && (!p || p.company !== m.company);
              return (
                <div key={m.id}>
                  {newCo && <div className="rr-sep"><span>{m.company}</span></div>}
                  <ChatMessage m={m} roster={roster} grouped={grouped && !newCo} byMid={byMid} selected={side?.type === "msg" && side.m.id === m.id}
                    onAgent={(cs) => setSide({ type: "agent", cs })} onCompany={setCompany} onSelect={(mm) => setSide({ type: "msg", m: mm })}
                    onReply={channel === "trace" ? undefined : reply} onCopy={copy} />
                </div>
              );
            })}
        </div>
        {newBelow > 0 && <button className="rr-new" onClick={toBottom}><Icon name="arrow-down" className="xs" />{newBelow} new message{newBelow === 1 ? "" : "s"}</button>}
        <div className="rr-typing">
          {answering.length > 0 && <><span className="typing-dots"><i /><i /><i /></span>{answering.map((cs) => <b key={cs} style={{ color: colorOf(roster, cs) }}>{cs}</b>)}<span>{answering.length === 1 ? "is" : "are"} typing…</span></>}
          {typing.length > 0 && <><span className="typing-dots"><i /><i /><i /></span>{typing.map((cs) => <b key={cs} style={{ color: colorOf(roster, cs) }}>{cs}</b>)}<span>{typing.length === 1 ? "is" : "are"} working{status[typing[0]]?.companies?.[0] ? ` on ${status[typing[0]].companies[0]}` : ""}…</span></>}
        </div>
        <Composer roster={roster} title={title} text={text} setText={setText} onSend={send} disabled={channel === "trace"} inputRef={inputRef} />
      </section>

      {side && (
        <aside className="rr-info" aria-labelledby="rr-info-t" onKeyDown={(e) => { if (e.key === "Escape") setSide(null); }}>
          <div className="rr-info-h">
            <h2 id="rr-info-t">{side.type === "agent" ? "Agent" : side.type === "msg" ? "Message" : "About this channel"}</h2>
            <span className="spacer" />
            <button className="ibtn sm" onClick={() => setSide(null)} aria-label="Close the details" title="Close (Esc)"><Icon name="close" className="xs" /></button>
          </div>
          <div className="rr-info-b">
            {side.type === "agent" && <AgentProfile cs={side.cs} roster={roster} status={status[side.cs]} messages={feed.messages}
              onMessage={(c) => open(c)} onChannel={(c) => open(c)} onPick={(cs) => roster.agents.some((a) => a.callsign === cs) && setSide({ type: "agent", cs })} />}
            {side.type === "msg" && <MessageDetail m={side.m} roster={roster} byMid={byMid} onAgent={(cs) => setSide({ type: "agent", cs })} />}
            {side.type === "channel" && (
              <div className="col" style={{ gap: 12 }}>
                <p className="small muted">{meta?.purpose ?? "A direct exchange between two agents."}</p>
                <div className="label">Members · {members.length}</div>
                {members.map((cs) => {
                  const a = agentOf(roster, cs);
                  const st = status[cs];
                  return (
                    <button key={cs} className="rr-agent" onClick={() => cs !== "YOU" && setSide({ type: "agent", cs })}>
                      <AgentAvatar role={a?.role ?? "user"} color={colorOf(roster, cs)} size={26} status={st?.state ?? "idle"} />
                      <span className="cs">{cs}</span><span className="grow ellipsis faint">{a?.title ?? "You"}</span>
                      {st?.state === "working" && <span className="xs" style={{ color: "var(--up)" }}>working</span>}
                    </button>
                  );
                })}
                <div className="label">This run</div>
                <div className="ap-stats">
                  <div><b>{counts[channel]?.count ?? 0}</b><span>messages</span></div>
                  <div><b>{companies.length}</b><span>companies</span></div>
                  <div><b>{ch.msgs.filter((m) => m.kind === "flag").length}</b><span>red flags</span></div>
                  <div><b>{prog?.saved ?? 0}</b><span>calls saved (run)</span></div>
                </div>
                {feed.live?.run && <span className="xs faint">Run #{feed.live.run.id} · {feed.live.run.mode} · started {feed.live.run.started?.replace("T", " ")} · {feed.live.run.finished ? `finished ${ago(Date.parse(feed.live.run.finished) / 1000)}` : "running"}</span>}
                <Link className="btn sm sec" to="/agents/network"><Icon name="type-hierarchy" className="xs" />Watch it on the Agent Network</Link>
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}

function MessageDetail({ m, roster, byMid, onAgent }: { m: Msg; roster: Roster; byMid: Map<string, Msg>; onAgent: (cs: string) => void }) {
  const k = KIND_META[m.kind];
  const d = m.data as Record<string, unknown>;
  const refs = m.refs.map((r) => byMid.get(r)).filter(Boolean) as Msg[];
  return (
    <div className="col" style={{ gap: 12 }}>
      <div className="row" style={{ gap: 8 }}>
        <span className="tag" style={{ color: k?.color }}><Icon name={k?.icon ?? "comment"} className="xs" />{k?.label ?? m.kind}</span>
        <span className="xs faint">{timeOf(m.ts)} · run #{m.run}</span>
      </div>
      <div className="row" style={{ gap: 8 }}>
        <button className="mention" style={{ ["--tc" as string]: colorOf(roster, m.sender) }} onClick={() => onAgent(m.sender)}>{m.sender}</button>
        {m.to && <><Icon name="arrow-right" className="xs faint" /><button className="mention" style={{ ["--tc" as string]: colorOf(roster, m.to) }} onClick={() => m.to !== "YOU" && onAgent(m.to!)}>{m.to}</button></>}
        {m.company && <span className="co-chip">{m.company}</span>}
      </div>
      <p className="small" style={{ lineHeight: 1.6 }}><RichText text={m.text} roster={roster} onAgent={onAgent} /></p>
      {refs.length > 0 && (
        <>
          <div className="label">{m.kind === "summary" ? "Findings combined into this report" : m.kind === "verdict" ? "Team reports behind this verdict" : "In reply to"}</div>
          {refs.map((r) => (
            <div key={r.mid} className="ap-msg"><span className="k" style={{ color: colorOf(roster, r.sender) }}>{r.sender}</span><span className="t">{r.text}</span></div>
          ))}
        </>
      )}
      {Object.keys(d).length > 0 && (
        <>
          <div className="label">Data carried</div>
          <pre className="rr-json">{JSON.stringify(d, null, 2)}</pre>
        </>
      )}
    </div>
  );
}

function Composer({ roster, title, text, setText, onSend, disabled, inputRef }: {
  roster: Roster; title: string; text: string; setText: (s: string) => void; onSend: () => void; disabled?: boolean;
  inputRef: React.RefObject<HTMLTextAreaElement>;
}) {
  const [hi, setHi] = useState(0);
  const word = /(^|\s)([/@][\w-]*)$/.exec(text)?.[2] ?? "";
  const options = useMemo(() => {
    if (word.startsWith("/")) return roster.commands.filter((c) => c.cmd.startsWith(word.toLowerCase()) || c.cmd.split(" ")[0].startsWith(word.toLowerCase())).map((c) => ({ value: c.cmd.split(" ")[0] + " ", label: c.cmd, help: c.help }));
    if (word.startsWith("@")) return roster.agents.filter((a) => a.role !== "system" && (a.callsign.toLowerCase().startsWith(word.slice(1).toLowerCase()) || a.title.toLowerCase().includes(word.slice(1).toLowerCase()))).slice(0, 8).map((a) => ({ value: `@${a.callsign} `, label: `@${a.callsign}`, help: a.title }));
    return [];
  }, [word, roster]);
  useEffect(() => setHi(0), [word]);
  const pick = (v: string) => setText(text.slice(0, text.length - word.length) + v);
  return (
    <div className={`rr-compose ${disabled ? "off" : ""}`}>
      {options.length > 0 && (
        <div className="rr-auto" id="rr-auto" role="listbox" aria-label={word.startsWith("/") ? "Commands" : "Agents"}>
          {options.map((o, i) => (
            <div key={o.label} id={`rr-auto-${i}`} role="option" aria-selected={i === hi} className={i === hi ? "on" : ""} onMouseDown={(e) => { e.preventDefault(); pick(o.value); }}>
              <b className="mono">{o.label}</b><span className="faint">{o.help}</span>
            </div>
          ))}
        </div>
      )}
      <textarea ref={inputRef} rows={1} value={text} disabled={disabled} aria-label={`Message ${title}`} role="combobox" aria-autocomplete="list"
        aria-expanded={options.length > 0} aria-controls="rr-auto" aria-activedescendant={options.length ? `rr-auto-${hi}` : undefined} placeholder={disabled ? "The trace is read-only" : `Message ${title} — ask, instruct ("focus on debt") or task ("re-check HAL"); @EQR-02 to address an agent`}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (options.length && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); setHi((h) => (h + (e.key === "ArrowDown" ? 1 : options.length - 1)) % options.length); return; }
          if (options.length && (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey && word.length > 0 && !text.endsWith(" ")))) { e.preventDefault(); pick(options[hi].value); return; }
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); }
        }} />
      <button className="btn" onClick={onSend} disabled={disabled} title="Send (Enter)" aria-label="Send"><Icon name="send" className="sm" /></button>
      <span className="rr-hint xs faint">Agents answer from their latest research (with an AI model when one is set up) and keep your instructions for the next run · <kbd>/help</kbd> commands · <kbd>Enter</kbd> send · <kbd>Shift Enter</kbd> new line</span>
    </div>
  );
}
