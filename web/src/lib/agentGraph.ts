// The Agent Network graph: where every node sits, how edges curve, and which
// way each kind of message travels. Pure geometry - no React.
import { Msg, Role, Roster } from "./agents";

// ------------------------------------------------------------ geometry
export type NKind = "agent" | "source" | "output";
export interface GNode { id: string; kind: NKind; x: number; y: number; w: number; h: number; team?: string; role?: Role; title: string; icon?: string }
export interface GEdge { id: string; from: string; to: string; kind: "input" | "report" | "command" | "consume" | "output" | "ops" }
export interface Frame { team: string; x: number; y: number; w: number; h: number }
export interface Pt { x: number; y: number }
export type Geom = [Pt, Pt, Pt, Pt];

export const TEAM_ORDER = ["NWS", "EQR", "IGR", "MAO", "IRV"];
export type Arrange = "hierarchy" | "radial";
export type Detail = "compact" | "full";
const OUTS = [
  { id: "OUT-VERDICT", title: "Verdicts & reports", icon: "verified" },
  { id: "OUT-ALERTS", title: "Alerts", icon: "bell" },
  { id: "OUT-ROOM", title: "Research Room", icon: "comment-discussion" },
];
const SRC_ICON: Record<string, string> = { "SRC-MKT": "graph-line", "SRC-NSE": "file-text", "SRC-NEWS": "rss", "SRC-ACC": "book", "SRC-LLM": "sparkle" };

/** Card sizes per detail level: compact cards carry the callsign and a short title only. */
function sizes(detail: Detail) {
  return detail === "compact"
    ? { aw: 124, ah: 46, lw: 144, lh: 50, cw: 180, ch: 70, ow: 144, oh: 46, r: 54 }
    : { aw: 142, ah: 80, lw: 160, lh: 84, cw: 200, ch: 108, ow: 160, oh: 80, r: 70 };
}

function edgesOf(r: Roster) {
  const edges: GEdge[] = [];
  const add = (from: string, to: string, kind: GEdge["kind"]) => edges.push({ id: `${from}>${to}`, from, to, kind });
  for (const [cs, srcs] of Object.entries(r.inputs)) for (const s of srcs) add(s, cs, "input");
  for (const a of r.agents) if (a.role === "analyst") add(a.callsign, `${a.team}-00`, "report");
  for (const t of TEAM_ORDER) add(`${t}-00`, "CMD-00", "command");
  add("OPS-00", "CMD-00", "ops");
  for (const o of OUTS) add("CMD-00", o.id, "output");
  for (const [consumer, providers] of Object.entries(r.consumes)) {
    if (consumer === "IRV-01" || consumer === "CMD-00") continue; // drawn only while traffic flows
    for (const p of providers) add(p, consumer, "consume");
  }
  return edges;
}

/** Rows of teams: sources on the left, analysts -> lead in each team band, the chief and outputs on the right. */
function hierarchy(r: Roster, detail: Detail) {
  const z = sizes(detail);
  const GAP = 14, FX = 200, FY = 24, FH = z.ah + 62, FS = FH + 22;
  const nodes: GNode[] = [], frames: Frame[] = [];
  const leadX = FX + 20 + 5 * (z.aw + GAP) + 14;
  TEAM_ORDER.forEach((code, i) => {
    const fy = FY + i * FS;
    frames.push({ team: code, x: FX, y: fy, w: leadX + z.lw + 20 - FX, h: FH });
    r.agents.filter((a) => a.team === code && a.role === "analyst").forEach((a, j) => {
      nodes.push({ id: a.callsign, kind: "agent", x: FX + 20 + j * (z.aw + GAP), y: fy + 38, w: z.aw, h: z.ah, team: code, role: a.role, title: a.title });
    });
    const lead = r.agents.find((a) => a.team === code && a.role === "lead");
    if (lead) nodes.push({ id: lead.callsign, kind: "agent", x: leadX, y: fy + 38 - (z.lh - z.ah) / 2, w: z.lw, h: z.lh, team: code, role: "lead", title: lead.title });
  });
  const midY = FY + (TEAM_ORDER.length * FS - (FS - FH)) / 2;
  const cx = leadX + z.lw + 120;
  nodes.push({ id: "CMD-00", kind: "agent", x: cx, y: midY - z.ch / 2, w: z.cw, h: z.ch, team: "CMD", role: "chief", title: "Chief Market Intelligence Officer" });
  nodes.push({ id: "OPS-00", kind: "agent", x: cx + (z.cw - z.ow) / 2, y: FY + 6, w: z.ow, h: z.oh, team: "OPS", role: "system", title: "Run Orchestrator" });
  OUTS.forEach((o, i) => nodes.push({ id: o.id, kind: "output", x: cx + z.cw + 120, y: midY - z.r / 2 + (i - 1) * (z.r + 64), w: z.r, h: z.r, title: o.title, icon: o.icon }));
  const srcs = Object.entries(r.sources);
  const srcStep = (TEAM_ORDER.length * FS - z.r) / Math.max(1, srcs.length - 1);
  srcs.forEach(([id, s], i) => nodes.push({ id, kind: "source", x: 40, y: FY + i * srcStep, w: z.r, h: z.r, title: s.title, icon: SRC_ICON[id] }));
  return { nodes, frames, width: cx + z.cw + 120 + z.r + 60, height: FY + TEAM_ORDER.length * FS + 30 };
}

/** The chief in the middle, leads on an inner ring, their analysts fanned outside, data sources on the rim. */
function radial(r: Roster, detail: Detail) {
  const z = sizes(detail);
  const R1 = detail === "compact" ? 210 : 250, R2 = detail === "compact" ? 430 : 520;
  let outer = R2;
  const nodes: GNode[] = [];
  const at = (deg: number, rad: number, w: number, h: number) => ({ x: Math.cos((deg * Math.PI) / 180) * rad - w / 2, y: Math.sin((deg * Math.PI) / 180) * rad - h / 2 });
  const angleOf: Record<string, number> = {};
  TEAM_ORDER.forEach((code, i) => {
    const a = -90 + i * 72;
    const lead = r.agents.find((x) => x.team === code && x.role === "lead");
    if (lead) { nodes.push({ id: lead.callsign, kind: "agent", ...at(a, R1, z.lw, z.lh), w: z.lw, h: z.lh, team: code, role: "lead", title: lead.title }); angleOf[lead.callsign] = a; }
    const team = r.agents.filter((x) => x.team === code && x.role === "analyst");
    // neighbours sit side by side near the top and bottom of the ring and stacked at its sides:
    // space them by the card's extent along the ring, and push the ring out when the fan would pass 68 degrees
    const rad = (a * Math.PI) / 180;
    const need = Math.abs(Math.sin(rad)) * (z.aw + 14) + Math.abs(Math.cos(rad)) * (z.ah + 14);
    const fan = 68 / Math.max(1, team.length - 1);
    const R = Math.max(R2, need / (2 * Math.sin(((fan * Math.PI) / 180) / 2)));
    outer = Math.max(outer, R);
    const step = Math.min(fan, (2 * Math.asin(Math.min(1, need / (2 * R))) * 180) / Math.PI);
    team.forEach((x, j) => {
      const aa = a + (j - (team.length - 1) / 2) * step;
      angleOf[x.callsign] = aa;
      nodes.push({ id: x.callsign, kind: "agent", ...at(aa, R, z.aw, z.ah), w: z.aw, h: z.ah, team: code, role: "analyst", title: x.title });
    });
  });
  nodes.push({ id: "CMD-00", kind: "agent", x: -z.cw / 2, y: -z.ch / 2, w: z.cw, h: z.ch, team: "CMD", role: "chief", title: "Chief Market Intelligence Officer" });
  nodes.push({ id: "OPS-00", kind: "agent", x: -z.ow / 2, y: -z.ch / 2 - z.oh - 60, w: z.ow, h: z.oh, team: "OPS", role: "system", title: "Run Orchestrator" });
  OUTS.forEach((o, i) => nodes.push({ id: o.id, kind: "output", x: (i - 1) * (z.r + 46) - z.r / 2, y: z.ch / 2 + 30, w: z.r, h: z.r, title: o.title, icon: o.icon }));
  // each source sits at the mean angle of the analysts that read it, nudged apart
  const placed = Object.entries(r.sources).map(([id, s]) => {
    const users = Object.entries(r.inputs).filter(([, v]) => v.includes(id)).map(([cs]) => angleOf[cs]).filter((x) => x !== undefined);
    const mx = users.reduce((t, a) => t + Math.cos((a * Math.PI) / 180), 0), my = users.reduce((t, a) => t + Math.sin((a * Math.PI) / 180), 0);
    return { id, s, a: users.length ? (Math.atan2(my, mx) * 180) / Math.PI : 180 };
  }).sort((p, q) => p.a - q.a);
  for (let k = 1; k < placed.length; k++) if (placed[k].a - placed[k - 1].a < 26) placed[k].a = placed[k - 1].a + 26;
  for (const p of placed) nodes.push({ id: p.id, kind: "source", ...at(p.a, outer + 210, z.r, z.r), w: z.r, h: z.r, title: p.s.title, icon: SRC_ICON[p.id] });
  // shift everything into positive space
  const minX = Math.min(...nodes.map((n) => n.x)) - 60, minY = Math.min(...nodes.map((n) => n.y)) - 60;
  for (const n of nodes) { n.x -= minX; n.y -= minY; }
  return { nodes, frames: [] as Frame[], width: Math.max(...nodes.map((n) => n.x + n.w)) + 60, height: Math.max(...nodes.map((n) => n.y + n.h)) + 60 };
}

export function layout(r: Roster, arrange: Arrange = "hierarchy", detail: Detail = "compact") {
  const g = arrange === "radial" ? radial(r, detail) : hierarchy(r, detail);
  return { ...g, edges: edgesOf(r) };
}

export type Layout = ReturnType<typeof layout>;

export const center = (n: GNode): Pt => ({ x: n.x + n.w / 2, y: n.y + n.h / 2 });
export function geom(a: GNode, b: GNode): Geom {
  const A = center(a), B = center(b);
  const dx = B.x - A.x, dy = B.y - A.y;
  if (Math.abs(dx) >= Math.abs(dy) * 0.7) {
    const s = Math.sign(dx) || 1;
    const p0 = { x: A.x + (s * a.w) / 2, y: A.y }, p3 = { x: B.x - (s * b.w) / 2, y: B.y };
    const c = Math.max(46, Math.abs(p3.x - p0.x) / 2);
    return [p0, { x: p0.x + s * c, y: p0.y }, { x: p3.x - s * c, y: p3.y }, p3];
  }
  const s = Math.sign(dy) || 1;
  const p0 = { x: A.x, y: A.y + (s * a.h) / 2 }, p3 = { x: B.x, y: B.y - (s * b.h) / 2 };
  const c = Math.max(40, Math.abs(p3.y - p0.y) / 2);
  return [p0, { x: p0.x, y: p0.y + s * c }, { x: p3.x, y: p3.y - s * c }, p3];
}
export const pathD = (g: Geom) => `M${g[0].x},${g[0].y} C${g[1].x},${g[1].y} ${g[2].x},${g[2].y} ${g[3].x},${g[3].y}`;
export function at(g: Geom, t: number): Pt {
  const u = 1 - t;
  const a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
  return { x: a * g[0].x + b * g[1].x + c * g[2].x + d * g[3].x, y: a * g[0].y + b * g[1].y + c * g[2].y + d * g[3].y };
}

/** Which way a message travels on the graph. */
export function routes(m: Msg): [string, string][] {
  const d = m.data as Record<string, unknown>;
  switch (m.kind) {
    case "fetch": return d.source ? [[String(d.source), m.sender]] : [];
    case "share": return m.to ? [[m.sender, m.to]] : [];
    case "task":
      if (m.sender === "CMD-00") return TEAM_ORDER.map((t) => ["CMD-00", `${t}-00`] as [string, string]);
      return ((d.members as string[]) ?? []).map((cs) => [m.sender, cs] as [string, string]);
    case "finding": case "flag":
      return m.sender.endsWith("-00") ? [] : [[m.sender, `${m.sender.slice(0, 3)}-00`]];
    case "summary": return [[m.sender, "CMD-00"]];
    case "verdict": return m.company ? [["CMD-00", "OUT-VERDICT"], ...(Number(d.flags) > 0 ? [["CMD-00", "OUT-ALERTS"] as [string, string]] : [])] : [["CMD-00", "OUT-ROOM"]];
    case "request": case "reply": case "review": return m.to && m.to !== "YOU" ? [[m.sender, m.to]] : m.to === "YOU" ? [[m.sender, "OUT-ROOM"]] : [];
    case "system": return [["OPS-00", "CMD-00"]];
    case "user": return [["OUT-ROOM", m.channel.startsWith("dm:") ? m.channel.slice(3).split("|").find((x) => x !== "YOU") ?? "CMD-00" : "CMD-00"]];
    default: return [];
  }
}

export const fmtClock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
