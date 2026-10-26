import { ReactNode, useEffect, useRef, useState } from "react";
import { agentOf, colorOf, KIND_META, Msg, Roster, timeOf } from "../lib/agents";
import { isNum, money, pct, titleCase } from "../lib/format";
import { AgentAvatar } from "./AgentAvatar";
import { Diverge, Icon, LabelBadge, Meter } from "./ui";

/** Text with @CALLSIGN mentions turned into clickable chips. */
export function RichText({ text, roster, onAgent }: { text: string; roster: Roster; onAgent: (cs: string) => void }) {
  const parts: ReactNode[] = [];
  const re = /@([A-Z]{3}-\d{2}|YOU)\b/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const cs = m[1];
    parts.push(
      <button key={m.index} className={`mention ${cs === "YOU" ? "me" : ""}`} style={{ ["--tc" as string]: colorOf(roster, cs) }}
        onClick={(e) => { e.stopPropagation(); if (cs !== "YOU") onAgent(cs); }}>@{cs}</button>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

export function ChatMessage({ m, roster, grouped, byMid, onAgent, onCompany, onSelect, onReply, onCopy, selected }: {
  m: Msg;
  roster: Roster;
  grouped: boolean;
  byMid: Map<string, Msg>;
  onAgent: (cs: string) => void;
  onCompany: (c: string) => void;
  onSelect: (m: Msg) => void;
  onReply?: (m: Msg) => void;
  onCopy?: (m: Msg) => void;
  selected?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const [menuUp, setMenuUp] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  // near the bottom of the feed the menu opens upward instead of being cut off
  const toggleMenu = () => {
    const el = menuRef.current, feed = el?.closest(".rr-msgs");
    if (el && feed && !menu) setMenuUp(feed.getBoundingClientRect().bottom - el.getBoundingClientRect().bottom < 120);
    setMenu(!menu);
  };
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenu(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    document.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [menu]);
  const me = m.sender === "YOU";
  const a = agentOf(roster, m.sender);
  const color = me ? roster.user.color : colorOf(roster, m.sender);
  const k = KIND_META[m.kind] ?? KIND_META.system;
  const d = m.data as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  const quoted = m.kind === "reply" && m.refs[0] ? byMid.get(m.refs[0]) : undefined;
  const ev = (d.evidence as { id: string; source: string; title: string; url: string; date: string }[] | undefined) ?? [];
  // the message's actions: icon buttons in the header line, or a small menu in the gutter of a
  // follow-on message - never floating over the text
  const actions = [
    !me && onReply && m.sender !== "OPS-00" ? { icon: "reply", label: `Reply to ${m.sender}`, run: () => onReply(m) } : null,
    { icon: "info", label: "Details: the data it carried and what it refers to", run: () => onSelect(m) },
    onCopy ? { icon: "copy", label: "Copy the text", run: () => onCopy(m) } : null,
    m.company ? { icon: "filter", label: `Show only ${m.company}`, run: () => onCompany(m.company!) } : null,
  ].filter(Boolean) as { icon: string; label: string; run: () => void }[];
  return (
    <div className={`msg k-${m.kind} ${grouped ? "grouped" : ""} ${me ? "mine" : ""} ${m.to === "YOU" ? "tome" : ""} ${selected ? "sel" : ""}`}
      style={{ ["--tc" as string]: color }}>
      <div className="msg-av">
        {!grouped && (me ? <AgentAvatar role="user" color={color} size={34} /> : <button className="av-btn" onClick={(e) => { e.stopPropagation(); onAgent(m.sender); }}><AgentAvatar role={a?.role ?? "system"} color={color} size={34} /></button>)}
        {grouped && (
          <div className="msg-gut" ref={menuRef}>
            <span className="msg-time-g">{timeOf(m.ts).slice(0, 5)}</span>
            <button className={`msg-more ${menu ? "on" : ""}`} onClick={(e) => { e.stopPropagation(); toggleMenu(); }} title="Message actions" aria-haspopup="menu" aria-expanded={menu}><Icon name="ellipsis" className="xs" /></button>
            {menu && (
              <div className={`msg-menu ${menuUp ? "up" : ""}`} role="menu">
                {actions.map((x) => <button key={x.icon} role="menuitem" onClick={() => { setMenu(false); x.run(); }}><Icon name={x.icon} className="xs" />{x.label}</button>)}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="msg-b">
        {!grouped && (
          <div className="msg-h">
            {me ? <b className="who">You</b> : <button className="who" onClick={(e) => { e.stopPropagation(); onAgent(m.sender); }}>{a?.title ?? m.sender}</button>}
            {!me && <span className="cs">{m.sender}</span>}
            {m.kind !== "user" && <span className="msg-kchip" style={{ color: k.color }}><Icon name={k.icon} className="xs" />{k.label}</span>}
            {d.llm && <span className="tag hm xs" title="Written by the agent's LLM from its latest research">AI</span>}
            <span className="time">{timeOf(m.ts)}</span>
            <span className="msg-acts" role="toolbar" aria-label="Message actions">
              {actions.map((x) => <button key={x.icon} onClick={(e) => { e.stopPropagation(); x.run(); }} title={x.label} aria-label={x.label}><Icon name={x.icon} className="xs" /></button>)}
            </span>
          </div>
        )}
        {quoted && (
          <div className="quote"><Icon name="reply" className="xs" /><b>{quoted.sender}</b> <span className="ellipsis">{quoted.text}</span></div>
        )}
        <div className="msg-t">
          {grouped && m.kind !== "user" && m.kind !== "reply" && <span className="msg-kchip g" style={{ color: k.color }}><Icon name={k.icon} className="xs" />{k.label}</span>}
          {m.company && !(m.kind === "reply" && m.text.slice(0, 60).toLowerCase().includes(m.company.replace(/ (Limited|Ltd\.?)$/i, "").toLowerCase())) && <button className="co-chip" onClick={(e) => { e.stopPropagation(); onCompany(m.company!); }}>{m.company.replace(/ Limited$/i, "")}</button>}
          <RichText text={m.company ? m.text.replace(new RegExp(`^${m.company.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}:\\s*`), "") : m.text} roster={roster} onAgent={onAgent} />
        </div>
        {(m.kind === "finding" || m.kind === "summary") && isNum(d.score) && (
          <div className="att">
            <span className="att-k">Score</span><Diverge value={d.score} width={70} /><span className="mono xs">{(d.score >= 0 ? "+" : "") + d.score.toFixed(2)}</span>
            <span className="att-k">Confidence</span><Meter value={(d.confidence ?? 0) * 100} width={50} /><span className="mono xs">{pct(d.confidence, 0)}</span>
            {d.used_llm && <span className="tag hm xs">LLM-assisted</span>}
            {d.validated === false && <span className="tag down xs">excluded by validation</span>}
            {m.kind === "summary" && m.refs.length > 0 && <span className="tag xs" title="This report combines its analysts' findings"><Icon name="git-merge" className="xs" />{m.refs.length} findings combined</span>}
            {d.status && d.status !== "ok" && <span className="tag xs">{d.status === "no_data" ? "no data" : d.status}</span>}
          </div>
        )}
        {m.kind === "finding" && d.signals && Object.keys(d.signals).length > 0 && (
          <div className="sigs">{Object.entries(d.signals as Record<string, number>).slice(0, 6).map(([kk, v]) => <span key={kk}>{titleCase(kk)} <b>{Math.abs(v) < 5 ? v.toFixed(2) : v.toLocaleString("en-IN", { maximumFractionDigits: 1 })}</b></span>)}</div>
        )}
        {m.kind === "verdict" && d.label && (
          <div className="att verdict">
            <LabelBadge label={d.label} />
            {isNum(d.value) && <span>HYBRID MODEL <b style={{ color: "var(--hm)" }}>{money(d.value, 0)}</b></span>}
            {isNum(d.price) && <span>price <b>{money(d.price, 0)}</b></span>}
            {isNum(d.upside) && <b className={d.upside >= 0 ? "up" : "down"}>{pct(d.upside, 1, true)}</b>}
            {isNum(d.confidence) && <span>confidence <b>{d.confidence.toFixed(0)}</b></span>}
          </div>
        )}
        {ev.length > 0 && (
          <div className="evs">
            <button className="ev-toggle" onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
              <Icon name={open ? "chevron-down" : "chevron-right"} className="xs" />{(d.evidence_count as number) ?? ev.length} evidence item{((d.evidence_count as number) ?? ev.length) === 1 ? "" : "s"}
            </button>
            {open && ev.map((e) => (
              <a key={e.id} className="ev-item" href={e.url || undefined} target="_blank" rel="noreferrer noopener" onClick={(x) => x.stopPropagation()}>
                <span className="mono xs faint">{e.id.slice(0, 7)}</span><span className="ellipsis">{e.title}</span><span className="xs faint">{e.source}{e.date ? ` · ${e.date.slice(0, 10)}` : ""}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
