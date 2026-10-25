import { Role } from "../lib/agents";

/** A robot glyph whose head tells the rank: the chief wears a star, leads two
 *  antennae, analysts one, the orchestrator a gear-like crown. */
export function BotGlyph({ role, size = 18, color = "currentColor" }: { role: Role | "user"; size?: number; color?: string }) {
  const p = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: color, strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (role === "user") return <svg {...p}><circle cx="12" cy="8" r="3.6" /><path d="M5 20c.8-3.6 3.6-5.6 7-5.6s6.2 2 7 5.6" /></svg>;
  return (
    <svg {...p}>
      {role === "chief" && <path d="M12 1.2l1 2 2.2.3-1.6 1.5.4 2.2L12 6.1 10 7.2l.4-2.2L8.8 3.5 11 3.2z" fill={color} stroke="none" />}
      {role === "lead" && <><path d="M8.5 7V4.2M15.5 7V4.2" /><circle cx="8.5" cy="3.4" r="1" fill={color} /><circle cx="15.5" cy="3.4" r="1" fill={color} /></>}
      {role === "analyst" && <><path d="M12 7V4.4" /><circle cx="12" cy="3.4" r="1.1" fill={color} /></>}
      {role === "system" && <path d="M9 7l1-2h4l1 2" />}
      <rect x="4.5" y="7.2" width="15" height="11.6" rx="3.2" />
      <circle cx="9.3" cy="12.4" r="1.25" fill={color} stroke="none" />
      <circle cx="14.7" cy="12.4" r="1.25" fill={color} stroke="none" />
      <path d="M9.8 15.8h4.4" />
      <path d="M2.6 11.5v2.8M21.4 11.5v2.8" />
    </svg>
  );
}

export function AgentAvatar({ role, color, size = 34, status, title }: { role: Role | "user"; color: string; size?: number; status?: string; title?: string }) {
  return (
    <span className={`av ${status ?? ""}`} title={title} style={{ width: size, height: size, ["--tc" as string]: color }}>
      <BotGlyph role={role} size={Math.round(size * 0.6)} color={color} />
      {status && <i className="av-dot" />}
    </span>
  );
}
