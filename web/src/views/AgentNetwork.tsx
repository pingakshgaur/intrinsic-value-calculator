import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { AgentStatus, colorOf, dmId, Kind, KIND_META, Msg, Role, Roster, timeOf, useAgentRuns, useLiveFeed, useRoster } from "../lib/agents";
import { ago } from "../lib/format";
import { LABEL_HEX } from "../lib/labels";
import { AgentAvatar, BotGlyph } from "../components/AgentAvatar";
import { AgentProfile } from "../components/AgentProfile";
import { ExportButton } from "../components/ExportButton";
import { Icon, PageHeader, Popover, QueryView, Toggle } from "../components/ui";
import { useApp } from "../components/workbenchContext";

// ------------------------------------------------------------ geometry
type NKind = "agent" | "source" | "output";
interface GNode { id: string; kind: NKind; x: number; y: number; w: number; h: number; team?: string; role?: Role; title: string; icon?: string }
interface GEdge { id: string; from: string; to: string; kind: "input" | "report" | "command" | "consume" | "output" | "ops" }
interface Frame { team: string; x: number; y: number; w: number; h: number }
interface Pt { x: number; y: number }
type Geom = [Pt, Pt, Pt, Pt];

const TEAM_ORDER = ["NWS", "EQR", "IGR", "MAO", "IRV"];
const AW = 132, AH = 66, GAP = 16, LW = 156, LH = 74, FX = 236, FY = 24, FH = 128, FS = 148;
const OUTS = [
  { id: "OUT-VERDICT", title: "Verdicts & reports", icon: "verified" },
  { id: "OUT-ALERTS", title: "Alerts", icon: "bell" },
  { id: "OUT-ROOM", title: "Research Room", icon: "comment-discussion" },
];
const SRC_ICON: Record<string, string> = { "SRC-MKT": "graph-line", "SRC-NSE": "file-text", "SRC-NEWS": "rss", "SRC-ACC": "book", "SRC-LLM": "sparkle" };

function layout(r: Roster) {
  const nodes: GNode[] = [], edges: GEdge[] = [], frames: Frame[] = [];
  const leadX = FX + 20 + 5 * (AW + GAP) + 14;
  TEAM_ORDER.forEach((code, i) => {
    const fy = FY + i * FS;
    frames.push({ team: code, x: FX, y: fy, w: leadX + LW + 20 - FX, h: FH });
    r.agents.filter((a) => a.team === code && a.role === "analyst").forEach((a, j) => {
      nodes.push({ id: a.callsign, kind: "agent", x: FX + 20 + j * (AW + GAP), y: fy + 44, w: AW, h: AH, team: code, role: a.role, title: a.title });
    });
    const lead = r.agents.find((a) => a.team === code && a.role === "lead");
    if (lead) nodes.push({ id: lead.callsign, kind: "agent", x: leadX, y: fy + 40, w: LW, h: LH, team: code, role: "lead", title: lead.title });
  });
  const midY = FY + (TEAM_ORDER.length * FS - (FS - FH)) / 2;
  const cx = leadX + LW + 130;
  nodes.push({ id: "CMD-00", kind: "agent", x: cx, y: midY - 50, w: 196, h: 100, team: "CMD", role: "chief", title: "Chief Market Intelligence Officer" });
  nodes.push({ id: "OPS-00", kind: "agent", x: cx + 20, y: FY + 6, w: 156, h: 62, team: "OPS", role: "system", title: "Run Orchestrator" });
  OUTS.forEach((o, i) => nodes.push({ id: o.id, kind: "output", x: cx + 330, y: midY - 160 + i * 130, w: 70, h: 70, title: o.title, icon: o.icon }));
  Object.entries(r.sources).forEach(([id, s], i) => nodes.push({ id, kind: "source", x: 40, y: FY + 40 + i * 132, w: 72, h: 72, title: s.title, icon: SRC_ICON[id] }));
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
  return { nodes, edges, frames, width: cx + 330 + 110, height: FY + TEAM_ORDER.length * FS + 10 };
}

const center = (n: GNode): Pt => ({ x: n.x + n.w / 2, y: n.y + n.h / 2 });
function geom(a: GNode, b: GNode): Geom {
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
const pathD = (g: Geom) => `M${g[0].x},${g[0].y} C${g[1].x},${g[1].y} ${g[2].x},${g[2].y} ${g[3].x},${g[3].y}`;
function at(g: Geom, t: number): Pt {
  const u = 1 - t;
  const a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
  return { x: a * g[0].x + b * g[1].x + c * g[2].x + d * g[3].x, y: a * g[0].y + b * g[1].y + c * g[2].y + d * g[3].y };
}

/** Which way a message travels on the graph. */
function routes(m: Msg): [string, string][] {
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

interface Packet { g: Geom; t0: number; dur: number; color: string; el: SVGGElement; edge?: string; to: string; kind: Kind; dir: Pt }
interface Spring { x: number; y: number; vx: number; vy: number }

// ------------------------------------------------------------ page
export function AgentNetwork() {
  const roster = useRoster();
  return (
    <div className="page fill an-page">
      <QueryView q={roster} rows={10}>{(r) => <Network roster={r} />}</QueryView>
    </div>
  );
}

function Network({ roster }: { roster: Roster }) {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const app = useApp();
  const runParam = params.get("run");
  const run = runParam ? Number(runParam) : null;
  const runs = useAgentRuns();
  const feed = useLiveFeed(run, 3000);
  const live = !!feed.live?.active && !run;
  const L = useMemo(() => layout(roster), [roster]);
  const [pos, setPos] = useState<Record<string, Pt>>(() => { try { return JSON.parse(localStorage.getItem("net.pos.v1") || "{}"); } catch { return {}; } });
  const nodes = useMemo(() => L.nodes.map((n) => (pos[n.id] ? { ...n, ...pos[n.id] } : n)), [L, pos]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const [view, setView] = useState({ x: 20, y: 10, k: 0.8 });
  const [tilt, setTilt] = useState(() => { try { return localStorage.getItem("net.tilt") === "1"; } catch { return false; } });
  const [labels, setLabels] = useState(true);
  const [srcEdges, setSrcEdges] = useState(true);
  const [sel, setSel] = useState<string | null>(params.get("focus"));
  const [selEdge, setSelEdge] = useState<string | null>(null);
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);
  const [edgeTip, setEdgeTip] = useState<{ id: string; x: number; y: number } | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; node: string | null } | null>(null);
  const [teams, setTeams] = useState<Set<string>>(new Set());
  const [kindsOff, setKindsOff] = useState<Set<Kind>>(new Set());
  const [find, setFind] = useState("");
  const [tab, setTab] = useState<"activity" | "agent" | "edge">(params.get("focus") ? "agent" : "activity");
  const stage = useRef<HTMLDivElement>(null);
  const [sw, setSw] = useState(1200);
  const [sideOpen, setSideOpen] = useState(() => window.innerWidth >= 1500);
  const [legendOpen, setLegendOpen] = useState<boolean | null>(null);
  const layer = useRef<SVGGElement>(null);
  const packets = useRef<Packet[]>([]);
  const hot = useRef<Map<string, number>>(new Map());
  const pulse = useRef<Map<string, number>>(new Map());
  const edgeEls = useRef<Map<string, SVGGElement>>(new Map());
  const nodeEls = useRef<Map<string, HTMLDivElement>>(new Map());
  const springs = useRef<Map<string, Spring>>(new Map());
  const heat = useRef<Map<string, number>>(new Map());
  const floats = useRef<HTMLDivElement>(null);
  const [, setFrame] = useState(0);
  const edgeCount = useRef<Map<string, number>>(new Map());

  // ---------- replay
  const [replay, setReplay] = useState<(Msg & { vt: number })[]>([]);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const clock = useRef(0);
  const cursor = useRef(0);
  const [clockShow, setClockShow] = useState(0);
  const replayRun = run ?? feed.live?.run?.id ?? null;
  const wasLive = useRef(false);
  useEffect(() => {
    if (live) { wasLive.current = true; return; }
    if (!replayRun) return;
    let stop = false;
    api.get<{ messages: Msg[] }>(`/api/agents/messages?run=${replayRun}&trace=true&limit=12000`).then((d) => {
      if (stop) return;
      // replay time: silent stretches (the base valuation) shrink to 2 seconds
      let vt = 0;
      const out = d.messages.map((m, i) => { if (i) vt += Math.min(2, Math.max(0, m.ts - d.messages[i - 1].ts)); return { ...m, vt }; });
      setReplay(out);
      if (wasLive.current && !run) {
        // a run that just finished live stays at its final state instead of restarting
        wasLive.current = false;
        const end = out.length ? out[out.length - 1].vt : 0;
        clock.current = end; cursor.current = out.length; setClockShow(end); setPlaying(false);
      } else { clock.current = 0; cursor.current = 0; setClockShow(0); setPlaying(true); }
    }).catch(() => undefined);
    return () => { stop = true; };
  }, [replayRun, live]);
  const span = replay.length ? Math.max(1, replay[replay.length - 1].vt) : 1;

  // ---------- spawning
  const kick = (id: string, dx: number, dy: number) => {
    const s = springs.current.get(id) ?? { x: 0, y: 0, vx: 0, vy: 0 };
    s.vx += dx; s.vy += dy;
    springs.current.set(id, s);
    heat.current.set(id, performance.now());
  };
  const floatFor = (m: Msg) => {
    const host = floats.current;
    if (!host || host.childElementCount > 40) return;
    const d = m.data as Record<string, unknown>;
    let at: string | null = null, text = "", cls = "";
    if (m.kind === "verdict" && m.company) { at = "CMD-00"; text = `${m.company.replace(/ (Limited|Ltd\.?)$/i, "")} · ${String(d.label ?? "")}`; cls = "verdict"; }
    else if (m.kind === "finding" && typeof d.score === "number") { at = m.sender; text = `${d.score >= 0 ? "+" : ""}${d.score.toFixed(2)}`; cls = d.score >= 0 ? "pos" : "neg"; }
    else if (m.kind === "summary" && typeof d.score === "number") { at = m.sender; text = `Σ ${d.score >= 0 ? "+" : ""}${d.score.toFixed(2)}`; cls = "sum"; }
    else if (m.kind === "flag") { at = m.sender; text = "⚑ red flag"; cls = "neg"; }
    else if (m.kind === "request") { at = m.sender; text = `? → ${m.to}`; cls = "req"; }
    if (!at) return;
    const n = byId.get(at);
    if (!n) return;
    const el = document.createElement("div");
    el.className = `an-float ${cls}`;
    el.textContent = text;
    el.style.left = `${n.x + n.w / 2}px`;
    el.style.top = `${n.y - 4}px`;
    if (cls === "verdict") el.style.setProperty("--fc", LABEL_HEX[String(d.label)] ?? "#e0b97f");
    host.appendChild(el);
    window.setTimeout(() => el.remove(), 2100);
  };
  const spawn = useCallback((m: Msg) => {
    if (kindsOff.has(m.kind) || !layer.current) return;
    floatFor(m);
    for (const [a, b] of routes(m)) {
      const A = byId.get(a), B = byId.get(b);
      if (!A || !B || A === B) continue;
      if (teams.size && !((A.team && teams.has(A.team)) || (B.team && teams.has(B.team)))) continue;
      if (packets.current.length > 140) return;
      const color = KIND_META[m.kind]?.color ?? "#9cdcfe";
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("class", "pk");
      g.innerHTML = `<circle r="9" fill="${color}" opacity=".18"/><circle r="4.2" fill="${color}"/><circle r="1.8" fill="#fff" opacity=".85"/>`;
      layer.current.appendChild(g);
      const edge = `${a}>${b}`;
      const dist = Math.hypot(B.x - A.x, B.y - A.y);
      const dir = { x: (B.x - A.x) / (dist || 1), y: (B.y - A.y) / (dist || 1) };
      packets.current.push({ g: geom(A, B), t0: performance.now(), dur: Math.min(1700, 520 + dist * 0.9), color, el: g, edge, to: b, kind: m.kind, dir });
      edgeCount.current.set(edge, (edgeCount.current.get(edge) ?? 0) + 1);
      pulse.current.set(a, performance.now());
      kick(a, -dir.x * 22, -dir.y * 22);  // the sender recoils
    }
  }, [byId, kindsOff, teams]); // eslint-disable-line react-hooks/exhaustive-deps

  // live: every new message becomes packets, staggered so bursts read as flow
  const spawned = useRef(0);
  const queue = useRef<Msg[]>([]);
  useEffect(() => {
    if (!live) return;
    const fresh = feed.messages.filter((m) => m.id > spawned.current);
    if (!fresh.length) return;
    if (!spawned.current) { spawned.current = fresh[fresh.length - 1].id; return; } // history is not replayed in live mode
    spawned.current = fresh[fresh.length - 1].id;
    queue.current.push(...fresh);
    // a tab left in the background comes back to the present, not to minutes of backlog
    if (queue.current.length > 90) queue.current = queue.current.slice(-45);
  }, [feed.messages, live]);

  // the animation loop: replay clock, live queue, packets, edge glow
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    let acc = 0;
    const loop = (now: number) => {
      const dt = Math.min(1, (now - last) / 1000); // a throttled background tab still keeps pace
      last = now;
      if (!live && playing && replay.length) {
        clock.current = Math.min(span, clock.current + dt * speed);
        let n = 0;
        while (cursor.current < replay.length && replay[cursor.current].vt <= clock.current && n < 14) { spawn(replay[cursor.current]); cursor.current++; n++; }
        if (cursor.current >= replay.length && !packets.current.length) setPlaying(false);
      }
      if (live) {
        acc += dt;
        while (queue.current.length && acc > 0.05) { spawn(queue.current.shift()!); acc -= 0.05; }
        if (!queue.current.length) acc = 0;
      }
      const keep: Packet[] = [];
      for (const p of packets.current) {
        const t = (now - p.t0) / p.dur;
        if (t >= 1) {
          p.el.remove();
          if (p.edge) hot.current.set(p.edge, now);
          pulse.current.set(p.to, now);
          kick(p.to, p.dir.x * 60, p.dir.y * 60);  // the receiver takes the hit
          continue;
        }
        const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
        const q = at(p.g, e);
        p.el.setAttribute("transform", `translate(${q.x},${q.y})`);
        if (p.edge) hot.current.set(p.edge, now);
        keep.push(p);
      }
      packets.current = keep;
      for (const [id, el] of edgeEls.current) {
        const h = hot.current.get(id);
        const v = h ? Math.max(0, 1 - (now - h) / 1400) : 0;
        el.style.setProperty("--hot", v.toFixed(3));
        el.style.setProperty("--vol", Math.min(1, Math.log2(1 + (edgeCount.current.get(id) ?? 0)) / 7).toFixed(3));
      }
      // springs: a node knocked by traffic swings and settles (fixed 60 Hz steps)
      for (let step = 0, left = dt; step < 8 && left > 0; step++, left -= 1 / 60) {
        const h = Math.min(1 / 60, left);
        for (const s of springs.current.values()) {
          s.vx += (-190 * s.x - 13 * s.vx) * h;
          s.vy += (-190 * s.y - 13 * s.vy) * h;
          s.x = Math.max(-7, Math.min(7, s.x + s.vx * h));
          s.y = Math.max(-7, Math.min(7, s.y + s.vy * h));
        }
      }
      for (const [id, s] of springs.current) {
        const el = nodeEls.current.get(id);
        const rest = Math.abs(s.x) + Math.abs(s.y) < 0.04 && Math.abs(s.vx) + Math.abs(s.vy) < 0.4;
        if (el) el.style.translate = rest ? "" : `${s.x.toFixed(2)}px ${s.y.toFixed(2)}px`;
        if (rest) springs.current.delete(id);
      }
      for (const [id, el] of nodeEls.current) {
        const h = heat.current.get(id);
        el.style.setProperty("--heat", (h ? Math.max(0, 1 - (now - h) / 2200) : 0).toFixed(3));
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    const ui = window.setInterval(() => { setFrame((f) => f + 1); setClockShow(clock.current); }, 250);
    return () => { cancelAnimationFrame(raf); window.clearInterval(ui); };
  }, [live, playing, replay, span, speed, spawn]);
  useEffect(() => () => { packets.current.forEach((p) => p.el.remove()); packets.current = []; }, []);
  const seek = (s: number) => {
    packets.current.forEach((p) => p.el.remove());
    packets.current = [];
    clock.current = s;
    cursor.current = replay.findIndex((m) => m.vt > s);
    if (cursor.current < 0) cursor.current = replay.length;
    setClockShow(s);
  };

  // ---------- status (live from the run, or derived from the replay clock)
  const status: Record<string, AgentStatus & { active?: boolean }> = useMemo(() => {
    if (live) return feed.live?.status ?? {};
    const out: Record<string, AgentStatus & { active?: boolean }> = {};
    const now = clockShow;
    for (let i = 0; i < cursor.current; i++) {
      const m = replay[i];
      if (!m) continue;
      const age = now - m.vt;
      const s = out[m.sender] ?? (out[m.sender] = { state: "done", companies: [], task: "", since: m.ts, done: 0, errors: 0, sent: 0, received: 0, llm: 0 });
      s.sent++;
      if (m.kind === "finding" || (m.kind === "verdict" && m.company)) s.done++;
      for (const [, b] of routes(m)) {
        const r = out[b] ?? (out[b] = { state: "done", companies: [], task: "", since: m.ts, done: 0, errors: 0, sent: 0, received: 0, llm: 0 });
        r.received++;
      }
      if (age < 2.2 / Math.max(1, speed / 4)) { s.state = "working"; if (m.company && !s.companies.includes(m.company)) s.companies = [m.company]; }
    }
    return out;
  }, [live, feed.live?.status, clockShow, replay, speed]);

  // ---------- running totals for the counters on the canvas
  const runNow = live ? feed.live?.run?.id : replayRun;
  const soFar = useMemo(() => (live ? feed.messages.filter((m) => m.run === runNow) : replay.slice(0, cursor.current)),
    [live, feed.messages, runNow, replay, clockShow]); // eslint-disable-line react-hooks/exhaustive-deps
  const tally = useMemo(() => {
    const c: Record<string, number> = {};
    let companies = 0, verdicts = 0, flags = 0, chat = 0;
    for (const m of soFar) {
      if (m.kind === "summary") c[`rep:${m.sender.slice(0, 3)}`] = (c[`rep:${m.sender.slice(0, 3)}`] ?? 0) + 1;
      if (m.kind === "fetch") { const s = String((m.data as Record<string, unknown>).source ?? ""); c[s] = (c[s] ?? 0) + 1; }
      if (m.channel !== "trace") { chat++; c[`team:${m.sender.slice(0, 3)}`] = (c[`team:${m.sender.slice(0, 3)}`] ?? 0) + 1; }
      if (m.kind === "task" && m.sender === "CMD-00") companies++;
      if (m.kind === "verdict" && m.company) verdicts++;
      if (m.kind === "flag") flags++;
    }
    const total = live ? (feed.live?.progress?.total ?? companies) : (replay.filter((m) => m.kind === "task" && m.sender === "CMD-00").length || companies);
    return { c, total: Math.max(total, verdicts), verdicts, flags, chat };
  }, [soFar, live, feed.live?.progress?.total, replay]);
  const ticker = soFar.filter((m) => m.channel !== "trace").slice(-4);

  // ---------- view: fit, zoom, pan
  const fit = useCallback(() => {
    const el = stage.current;
    if (!el) return;
    // leave room for the overlays: search and legend on top, tools and replay below
    const top = 92, bottom = 64, availH = el.clientHeight - top - bottom;
    const k = Math.min(1.25, Math.min((el.clientWidth - 40) / L.width, availH / L.height));
    setView({ k, x: (el.clientWidth - L.width * k) / 2, y: top + (availH - L.height * k) / 2 });
  }, [L]);
  useEffect(() => { const t = window.setTimeout(fit, 60); return () => window.clearTimeout(t); }, [fit, sideOpen]);
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSw(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const showLegend = legendOpen ?? sw >= 1050;
  const focus = useCallback((id: string) => {
    const n = byId.get(id), el = stage.current;
    if (!n || !el) return;
    const k = Math.max(view.k, 0.9);
    setView({ k, x: el.clientWidth / 2 - (n.x + n.w / 2) * k, y: el.clientHeight / 2 - (n.y + n.h / 2) * k });
    pulse.current.set(id, performance.now());
  }, [byId, view.k]);
  useEffect(() => { const f = params.get("focus"); if (f) { const t = window.setTimeout(() => focus(f), 120); return () => window.clearTimeout(t); } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const zoomAt = (factor: number, cx?: number, cy?: number) => setView((v) => {
    const el = stage.current!;
    const px = cx ?? el.clientWidth / 2, py = cy ?? el.clientHeight / 2;
    const k = Math.max(0.3, Math.min(2.4, v.k * factor));
    return { k, x: px - ((px - v.x) * k) / v.k, y: py - ((py - v.y) * k) / v.k };
  });
  const drag = useRef<{ mode: "pan" | "node"; id?: string; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const onDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    setMenu(null);
    const nodeEl = (e.target as HTMLElement).closest("[data-node]") as HTMLElement | null;
    if (nodeEl) {
      const id = nodeEl.dataset.node!;
      const n = byId.get(id)!;
      drag.current = { mode: "node", id, sx: e.clientX, sy: e.clientY, ox: n.x, oy: n.y, moved: false };
    } else if (!nodeEl) {
      drag.current = { mode: "pan", sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y, moved: false };
    }
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.sx, dy = e.clientY - d.sy;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    if (d.mode === "pan") setView((v) => ({ ...v, x: d.ox + dx, y: d.oy + dy }));
    else if (d.moved && !tilt) setPos((p) => ({ ...p, [d.id!]: { x: d.ox + dx / view.k, y: d.oy + dy / view.k } })); // in 2.5D nodes stay put
  };
  const onUp = () => {
    const d = drag.current;
    drag.current = null;
    if (d?.mode === "node" && d.moved) setPos((p) => { try { localStorage.setItem("net.pos.v1", JSON.stringify(p)); } catch { /* ignore */ } return p; });
    if (d?.mode === "node" && (!d.moved || tilt)) { setSel(d.id!); setSelEdge(null); setTab("agent"); setSideOpen(true); }
    if (d?.mode === "pan" && !d.moved) { setSel(null); setSelEdge(null); setTab("activity"); }
  };
  const onWheel = (e: React.WheelEvent) => {
    const r = stage.current!.getBoundingClientRect();
    zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top);
  };
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const stopScroll = (e: WheelEvent) => e.preventDefault();
    el.addEventListener("wheel", stopScroll, { passive: false });
    return () => el.removeEventListener("wheel", stopScroll);
  }, []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.key === "f" || e.key === "F") fit();
      else if (e.key === "+" || e.key === "=") zoomAt(1.2);
      else if (e.key === "-") zoomAt(1 / 1.2);
      else if (e.key === " " && !live) { e.preventDefault(); setPlaying((p) => !p); }
      else if (e.key === "Escape") { setSel(null); setSelEdge(null); setMenu(null); setTab("activity"); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [fit, live]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { localStorage.setItem("net.tilt", tilt ? "1" : "0"); } catch { /* ignore */ } }, [tilt]);
  useEffect(() => {
    if (!menu) return;
    const close = (e: PointerEvent) => { if (!(e.target as HTMLElement).closest(".tc-menu")) setMenu(null); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [menu]);

  // ---------- neighbourhood highlight
  const neigh = useMemo(() => {
    if (!sel) return null;
    const s = new Set([sel]);
    for (const e of L.edges) { if (e.from === sel) s.add(e.to); if (e.to === sel) s.add(e.from); }
    return s;
  }, [sel, L.edges]);
  const dimTeam = (team?: string) => teams.size > 0 && !(team && teams.has(team));
  const now = performance.now();
  const searchHits = find.trim() ? nodes.filter((n) => (n.id + " " + n.title).toLowerCase().includes(find.trim().toLowerCase())) : [];

  const prog = feed.live?.progress;
  const working = Object.entries(status).filter(([, s]) => s.state === "working");
  const recent = (live ? feed.messages : replay.slice(0, cursor.current)).filter((m) => m.channel !== "trace").slice(-40).reverse();
  const teamLoad = TEAM_ORDER.concat(["CMD"]).map((t) => ({ t, n: (live ? feed.messages : replay.slice(0, cursor.current)).filter((m) => m.sender.startsWith(t)).length }));
  const maxLoad = Math.max(1, ...teamLoad.map((x) => x.n));
  const edgeMsgs = selEdge ? (live ? feed.messages : replay).filter((m) => routes(m).some(([a, b]) => `${a}>${b}` === selEdge)).slice(-60).reverse() : [];
  const runInfo = feed.live?.run;

  const nodeMenu = (id: string) => {
    const a = roster.agents.find((x) => x.callsign === id);
    const team = a ? roster.teams[a.team] : null;
    return (
      <>
        <div className="tc-mh">{id} · {byId.get(id)?.title}</div>
        <button onClick={() => { setSel(id); setTab("agent"); setMenu(null); }}><Icon name="info" className="sm" />Inspect</button>
        <button onClick={() => { focus(id); setMenu(null); }}><Icon name="target" className="sm" />Centre on it</button>
        <button onClick={() => { setSel(id); setMenu(null); }}><Icon name="type-hierarchy" className="sm" />Highlight its connections</button>
        {team && <button onClick={() => nav(`/agents/chat?c=${team.channel}`)}><Icon name="comment-discussion" className="sm" />Open #{team.slug}</button>}
        {a && a.role !== "system" && <button onClick={() => nav(`/agents/chat?c=${encodeURIComponent(dmId(id, "YOU"))}`)}><Icon name="comment" className="sm" />Message {id}</button>}
        {team && a?.role !== "chief" && <button onClick={() => { setTeams(new Set([a!.team])); setMenu(null); }}><Icon name="filter" className="sm" />Show only {a!.team}</button>}
        <hr />
        <button onClick={() => { navigator.clipboard?.writeText(id); setMenu(null); app.toast(`Copied ${id}`); }}><Icon name="copy" className="sm" />Copy callsign</button>
        {pos[id] && <button onClick={() => { setPos((p) => { const n = { ...p }; delete n[id]; try { localStorage.setItem("net.pos.v1", JSON.stringify(n)); } catch { /* ignore */ } return n; }); setMenu(null); }}><Icon name="discard" className="sm" />Reset its position</button>}
      </>
    );
  };
  const canvasMenu = (
    <>
      <div className="tc-mh">Agent Network</div>
      <button onClick={() => { fit(); setMenu(null); }}><Icon name="screen-normal" className="sm" />Fit to screen <kbd>F</kbd></button>
      <button onClick={() => { setTilt(!tilt); setMenu(null); }}><Icon name={tilt ? "check" : "blank"} className="sm" />2.5D perspective</button>
      <button onClick={() => { setLabels(!labels); setMenu(null); }}><Icon name={labels ? "check" : "blank"} className="sm" />Edge labels</button>
      <button onClick={() => { setSrcEdges(!srcEdges); setMenu(null); }}><Icon name={srcEdges ? "check" : "blank"} className="sm" />Data-source edges</button>
      {!live && <button onClick={() => { setPlaying(!playing); setMenu(null); }}><Icon name={playing ? "debug-pause" : "play"} className="sm" />{playing ? "Pause replay" : "Play replay"} <kbd>Space</kbd></button>}
      <hr />
      <button onClick={() => { setTeams(new Set()); setKindsOff(new Set()); setMenu(null); }}><Icon name="clear-all" className="sm" />Clear filters</button>
      <button onClick={() => { setPos({}); try { localStorage.removeItem("net.pos.v1"); } catch { /* ignore */ } setMenu(null); }}><Icon name="discard" className="sm" />Reset layout</button>
    </>
  );

  return (
    <>
      <PageHeader crumbs={[{ label: "Research workforce" }, { label: "Agent Network" }]} title="Agent Network"
        sub={<span className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <span className={`live-dot ${live ? "on" : ""}`}>{live ? "Live run" : `Replay of run #${replayRun ?? "-"}`}</span>
          <span>{roster.agents.length - 1} agents in 6 teams · info-bits travel the edges as the agents exchange work</span>
        </span>}
        actions={<>
          <select className="sel" value={run ?? ""} onChange={(e) => { const p = new URLSearchParams(params); if (e.target.value) p.set("run", e.target.value); else p.delete("run"); setParams(p, { replace: true }); }}>
            <option value="">{feed.live?.active ? "Live run" : "Latest run"}{runInfo ? ` (#${runInfo.id})` : ""}</option>
            {(runs.data ?? []).map((r) => <option key={r.id} value={r.id}>#{r.id} · {r.mode} · {r.started?.slice(5, 16).replace("T", " ")}</option>)}
          </select>
          <WorkforceControl active={!!feed.live?.active} />
          <button className="btn sec" onClick={() => nav("/agents/chat")}><Icon name="comment-discussion" className="sm" />Research Room</button>
          <button className={`btn sec ${sideOpen ? "on" : ""}`} onClick={() => setSideOpen(!sideOpen)} title="Show or hide the inspector"><Icon name="layout-sidebar-right" className="sm" />Inspector</button>
        </>} />
      <div className={`an ${sideOpen ? "" : "noside"}`}>
        <div className={`an-stage ${tilt ? "tilt" : ""}`} ref={stage} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onWheel={onWheel}
          onContextMenu={(e) => { e.preventDefault(); const n = (e.target as HTMLElement).closest("[data-node]") as HTMLElement | null; setMenu({ x: e.clientX, y: e.clientY, node: n?.dataset.node ?? null }); }}>
          <div className="an-tilt">
          <div className="an-world" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`, width: L.width, height: L.height }}>
            {L.frames.map((f) => {
              const t = roster.teams[f.team];
              const busy = roster.agents.filter((a) => a.team === f.team && status[a.callsign]?.state === "working").length;
              return (
                <div key={f.team} className={`an-frame ${dimTeam(f.team) ? "dim" : ""}`} style={{ left: f.x, top: f.y, width: f.w, height: f.h, ["--tc" as string]: t.color }}>
                  <span className="an-frame-h"><b>{f.team}</b> {t.name}{busy > 0 && <em>{busy} working</em>}
                    <span key={tally.c[`team:${f.team}`] ?? 0} className="an-frame-n bump">{tally.c[`team:${f.team}`] ?? 0} msgs</span></span>
                  <i className="an-frame-bar" style={{ width: `${Math.min(100, (100 * (tally.c[`rep:${f.team}`] ?? 0)) / Math.max(1, tally.total))}%` }} />
                </div>
              );
            })}
            <svg className="an-svg" width={L.width} height={L.height}>
              <defs>
                <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
              </defs>
              {L.edges.map((e) => {
                const a = byId.get(e.from), b = byId.get(e.to);
                if (!a || !b || (!srcEdges && e.kind === "input")) return null;
                const dim = (neigh && !(neigh.has(e.from) && neigh.has(e.to))) || (teams.size && !((a.team && teams.has(a.team)) || (b.team && teams.has(b.team))));
                const color = e.kind === "input" ? "#57a3f8" : e.kind === "consume" ? "#f0a35e" : e.kind === "output" ? "#e0b97f" : colorOf(roster, e.from);
                const g = geom(a, b);
                const mid = at(g, 0.5);
                return (
                  <g key={e.id} ref={(el) => { if (el) edgeEls.current.set(e.id, el); else edgeEls.current.delete(e.id); }}
                    className={`an-edge k-${e.kind} ${dim ? "dim" : ""} ${selEdge === e.id ? "sel" : ""}`} style={{ ["--ec" as string]: color }}>
                    <path d={pathD(g)} className="line" />
                    <path d={pathD(g)} className="flow" />
                    <path d={pathD(g)} className="hit" onPointerEnter={(ev) => setEdgeTip({ id: e.id, x: ev.clientX, y: ev.clientY })} onPointerLeave={() => setEdgeTip(null)}
                      onPointerDown={(ev) => { ev.stopPropagation(); setSelEdge(e.id); setSel(null); setTab("edge"); }} />
                    {labels && e.kind === "command" && <text x={mid.x} y={mid.y - 6} className="an-elabel">team report</text>}
                    {labels && e.kind === "consume" && <text x={mid.x} y={mid.y - 6} className="an-elabel">cross-team read</text>}
                  </g>
                );
              })}
              <g ref={layer} filter="url(#glow)" />
            </svg>
            <div className="an-floats" ref={floats} />
            {nodes.map((n) => {
              const st = status[n.id];
              const isSel = sel === n.id;
              const dim = (neigh && !neigh.has(n.id)) || dimTeam(n.team) || (searchHits.length > 0 && !searchHits.includes(n));
              const color = n.kind === "source" ? "#57a3f8" : n.kind === "output" ? "#e0b97f" : colorOf(roster, n.id);
              const p = pulse.current.get(n.id);
              const pulsing = p && now - p < 700;
              if (n.kind !== "agent") {
                return (
                  <div key={n.id} data-node={n.id} ref={(el) => { if (el) nodeEls.current.set(n.id, el); else nodeEls.current.delete(n.id); }}
                    className={`an-node round ${dim ? "dim" : ""} ${isSel ? "sel" : ""} ${pulsing ? "pulse" : ""}`}
                    style={{ left: n.x, top: n.y, width: n.w, height: n.h, ["--tc" as string]: color }}
                    onPointerEnter={(e) => setHover({ id: n.id, x: e.clientX, y: e.clientY })} onPointerLeave={() => setHover(null)}>
                    <Icon name={n.icon ?? "circle"} />
                    {(() => {
                      const v = n.id === "OUT-VERDICT" ? tally.verdicts : n.id === "OUT-ALERTS" ? tally.flags : n.id === "OUT-ROOM" ? tally.chat : tally.c[n.id] ?? 0;
                      return v > 0 ? <span key={v} className="an-count bump">{v}</span> : null;
                    })()}
                    <span className="an-cap">{n.title}</span>
                  </div>
                );
              }
              const state = st?.state ?? "idle";
              return (
                <div key={n.id} data-node={n.id} ref={(el) => { if (el) nodeEls.current.set(n.id, el); else nodeEls.current.delete(n.id); }}
                  className={`an-node card r-${n.role} s-${state} ${dim ? "dim" : ""} ${isSel ? "sel" : ""} ${pulsing ? "pulse" : ""}`}
                  style={{ left: n.x, top: n.y, width: n.w, height: n.h, ["--tc" as string]: color }}
                  onPointerEnter={(e) => setHover({ id: n.id, x: e.clientX, y: e.clientY })} onPointerMove={(e) => setHover({ id: n.id, x: e.clientX, y: e.clientY })} onPointerLeave={() => setHover(null)}
                  onDoubleClick={() => { const a = roster.agents.find((x) => x.callsign === n.id); if (a) nav(`/agents/chat?c=${roster.teams[a.team].channel}`); }}>
                  <span className="port l" /><span className="port r" />
                  <div className="an-top">
                    <span className="an-ic"><BotGlyph role={n.role ?? "analyst"} size={n.role === "chief" ? 22 : 17} color={color} />
                      {n.role === "chief" && tally.total > 0 && (
                        <svg className="an-ring" viewBox="0 0 44 44"><circle cx="22" cy="22" r="19" className="bg" />
                          <circle cx="22" cy="22" r="19" className="fg" style={{ strokeDasharray: `${(119.4 * tally.verdicts) / tally.total} 119.4` }} /></svg>
                      )}
                    </span>
                    <div className="an-id"><b>{n.id}</b><span>{n.role === "chief" ? "Chief" : n.role === "lead" ? "Team lead" : n.role === "system" ? "Orchestrator" : "Analyst"}</span></div>
                    <span className={`an-state s-${state}`} title={state} />
                  </div>
                  <div className="an-title">{n.title.replace(/ Analyst$/, "")}</div>
                  <div className="an-task">
                    <span className="grow ellipsis">{state === "working" ? <><span className="spin-ring" />{st?.companies?.[0]?.replace(/ Limited$/i, "") ?? "working"}</> : state === "error" ? "error" : n.role === "chief" && tally.total ? `${tally.verdicts}/${tally.total} verdicts` : st?.done ? `${st.done} done` : "idle"}</span>
                    {st && (st.sent > 0 || st.received > 0) && <span className="an-io"><b key={`s${st.sent}`} className="bump">↑{st.sent}</b><b key={`r${st.received}`} className="bump">↓{st.received}</b></span>}
                  </div>
                </div>
              );
            })}
          </div>
          </div>

          <div className="an-ov tl" data-noexport onPointerDown={(e) => e.stopPropagation()}>
            <div className="search sm"><Icon name="search" /><input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find agent (callsign or role)"
              onKeyDown={(e) => { if (e.key === "Enter" && searchHits[0]) { focus(searchHits[0].id); setSel(searchHits[0].id); setTab("agent"); } }} /></div>
            <div className="an-teams">
              {Object.entries(roster.teams).filter(([c]) => c !== "OPS").map(([code, t]) => (
                <button key={code} className={`chip ${teams.has(code) ? "on" : ""}`} onClick={() => setTeams((s) => { const n = new Set(s); if (n.has(code)) n.delete(code); else n.add(code); return n; })}>
                  <span className="sw" style={{ background: t.color }} />{code}
                </button>
              ))}
            </div>
            {ticker.length > 0 && (
              <div className="an-ticker">
                {ticker.slice(-3).map((m) => (
                  <div key={m.id} className="an-tick" title={m.text}>
                    <i style={{ background: KIND_META[m.kind]?.color }} /><b style={{ color: colorOf(roster, m.sender) }}>{m.sender}</b>
                    {m.to ? <span className="faint">→ {m.to}</span> : <span />}<span className="ellipsis">{m.text}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          {!showLegend ? (
            <button className="an-ov tr an-legend-btn" data-noexport onPointerDown={(e) => e.stopPropagation()} onClick={() => setLegendOpen(true)}>
              <span className="dots">{(["fetch", "finding", "summary", "verdict"] as Kind[]).map((k) => <i key={k} style={{ background: KIND_META[k].color }} />)}</span>Info-bits<Icon name="chevron-down" className="xs" />
            </button>
          ) : (
          <div className="an-ov tr an-legend" data-noexport onPointerDown={(e) => e.stopPropagation()}>
            <button className="label an-legend-x" onClick={() => setLegendOpen(false)} title="Fold the legend">Info-bits <Icon name="chevron-up" className="xs" /></button>
            {(["fetch", "share", "finding", "flag", "request", "reply", "review", "summary", "verdict", "task"] as Kind[]).map((k) => (
              <button key={k} className={kindsOff.has(k) ? "off" : ""} onClick={() => setKindsOff((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; })}>
                <i style={{ background: KIND_META[k].color, boxShadow: `0 0 8px ${KIND_META[k].color}` }} />{KIND_META[k].label}
              </button>
            ))}
            <span className="an-flow xs faint">evidence → finding → team report → verdict</span>
          </div>
          )}
          <div className="an-ov bl an-tools" data-noexport onPointerDown={(e) => e.stopPropagation()}>
            <button title="Fit (F)" onClick={fit}><Icon name="screen-normal" /></button>
            <button title="Zoom in (+)" onClick={() => zoomAt(1.2)}><Icon name="zoom-in" /></button>
            <button title="Zoom out (-)" onClick={() => zoomAt(1 / 1.2)}><Icon name="zoom-out" /></button>
            <button title="2.5D perspective" className={tilt ? "on" : ""} onClick={() => setTilt(!tilt)}><Icon name="layers" /></button>
            <button title="Reset layout" onClick={() => { setPos({}); try { localStorage.removeItem("net.pos.v1"); } catch { /* ignore */ } }}><Icon name="discard" /></button>
            <span className="an-zoom">{Math.round(view.k * 100)}%</span>
            <ExportButton title="Agent Network" target={stage} className="" />
          </div>
          {!live && replay.length > 0 && (
            <div className="an-ov bc an-transport" data-noexport onPointerDown={(e) => e.stopPropagation()} style={{ width: Math.max(300, Math.min(560, sw - (sw >= 760 ? 470 : 280))) }}>
              <button className="ibtn" onClick={() => { if (!playing && cursor.current >= replay.length) seek(0); setPlaying(!playing); }} title="Play / pause (Space)"><Icon name={playing ? "debug-pause" : "play"} /></button>
              <Density replay={replay} span={span} />
              <input type="range" className="sl" min={0} max={span} step={0.1} value={clockShow} onChange={(e) => seek(Number(e.target.value))} />
              <span className="mono xs">{fmtClock(clockShow)} / {fmtClock(span)}</span>
              <select className="sel sm" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>{[1, 2, 4, 8, 16].map((s) => <option key={s} value={s}>{s}×</option>)}</select>
            </div>
          )}
          {sw >= 760 && <MiniMap L={L} nodes={nodes} view={view} stage={stage} onJump={(x, y) => { const el = stage.current!; setView((v) => ({ ...v, x: el.clientWidth / 2 - x * v.k, y: el.clientHeight / 2 - y * v.k })); }} roster={roster} />}
          {hover && !menu && <NodeTip id={hover.id} x={hover.x} y={hover.y} roster={roster} status={status[hover.id]} node={byId.get(hover.id)} />}
          {edgeTip && !menu && (() => {
            const [a, b] = edgeTip.id.split(">");
            const e = L.edges.find((x) => x.id === edgeTip.id);
            return (
              <div className="an-tip" style={{ left: edgeTip.x + 14, top: edgeTip.y + 12 }}>
                <b>{a} → {b}</b>
                <div className="xs muted">{e?.kind === "input" ? "data feed" : e?.kind === "report" ? "findings to the lead" : e?.kind === "command" ? "team report to the chief" : e?.kind === "consume" ? "cross-team read" : e?.kind === "output" ? "verdicts out" : "run control"}</div>
                <div className="xs faint">{edgeCount.current.get(edgeTip.id) ?? 0} info-bits so far · click for the messages</div>
              </div>
            );
          })()}
          {menu && (
            <div className="tc-menu" style={{ left: Math.min(menu.x, window.innerWidth - 270), top: Math.min(menu.y, window.innerHeight - 330) }} onPointerDown={(e) => e.stopPropagation()}>
              {menu.node ? nodeMenu(menu.node) : canvasMenu}
            </div>
          )}
        </div>

        {sideOpen && <aside className="an-side">
          <div className="an-tabs">
            <button className={tab === "activity" ? "on" : ""} onClick={() => setTab("activity")}><Icon name="pulse" className="xs" />Activity</button>
            <button className={tab === "agent" ? "on" : ""} onClick={() => setTab("agent")} disabled={!sel}><Icon name="hubot" className="xs" />Agent</button>
            <button className={tab === "edge" ? "on" : ""} onClick={() => setTab("edge")} disabled={!selEdge}><Icon name="arrow-swap" className="xs" />Edge</button>
          </div>
          <div className="an-side-b">
            {tab === "agent" && sel && roster.agents.some((a) => a.callsign === sel) ? (
              <AgentProfile cs={sel} roster={roster} status={status[sel]} messages={live ? feed.messages : replay.slice(0, cursor.current)} graphLink={false}
                onMessage={(c) => nav(`/agents/chat?c=${encodeURIComponent(c)}`)} onChannel={(c) => nav(`/agents/chat?c=${c}`)}
                onPick={(cs) => { if (byId.has(cs)) { setSel(cs); focus(cs); } }} />
            ) : tab === "agent" && sel ? (
              <div className="col" style={{ gap: 8 }}><b>{byId.get(sel)?.title}</b><span className="small muted">{roster.sources[sel]?.detail ?? "Where the chief's work goes."}</span></div>
            ) : tab === "edge" && selEdge ? (
              <div className="col" style={{ gap: 8 }}>
                <b>{selEdge.replace(">", " → ")}</b>
                <span className="xs faint">{edgeMsgs.length} message{edgeMsgs.length === 1 ? "" : "s"} travelled this edge{live ? "" : " in the replay"}</span>
                {edgeMsgs.map((m) => (
                  <div key={m.id} className="ap-msg"><span className="k" style={{ color: KIND_META[m.kind]?.color }}>{KIND_META[m.kind]?.label}</span><span className="t">{m.text}</span><span className="xs faint">{timeOf(m.ts)}</span></div>
                ))}
              </div>
            ) : (
              <div className="col" style={{ gap: 14 }}>
                <div className="an-run">
                  <div className="row"><b>Run #{runInfo?.id ?? replayRun ?? "-"}</b><span className="tag xs">{runInfo?.mode ?? ""}</span><span className="spacer" /><span className={`live-dot ${live ? "on" : ""}`}>{live ? "live" : runInfo?.finished ? `finished ${ago(Date.parse(runInfo.finished) / 1000)}` : ""}</span></div>
                  {prog && <div className="rr-prog"><div style={{ width: `${(100 * prog.done) / Math.max(1, prog.total)}%` }} /><span>{prog.done}/{prog.total} companies</span></div>}
                  <div className="ap-stats">
                    <div><b>{prog?.messages ?? 0}</b><span>messages</span></div>
                    <div><b>{prog?.fetched ?? 0}</b><span>feeds fetched</span></div>
                    <div><b>{prog?.saved ?? 0}</b><span>calls saved by sharing</span></div>
                    <div><b>{runInfo?.llm_calls ?? 0}</b><span>LLM calls</span></div>
                  </div>
                </div>
                <div>
                  <div className="label" style={{ marginBottom: 6 }}>Working now · {working.length}</div>
                  {working.length === 0 ? <span className="xs faint">{live ? "Between companies." : playing ? "…" : "Nobody - the run is over. Press play to replay it."}</span> : working.slice(0, 12).map(([cs, s]) => (
                    <button key={cs} className="rr-agent" onClick={() => { setSel(cs); setTab("agent"); focus(cs); }}>
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
                  {recent.slice(0, 18).map((m) => (
                    <button key={m.id} className="an-feed" onClick={() => { setSel(m.sender); setTab("agent"); focus(m.sender); }}>
                      <i style={{ background: KIND_META[m.kind]?.color }} /><b style={{ color: colorOf(roster, m.sender) }}>{m.sender}</b>{m.to && <span className="faint">→ {m.to}</span>}<span className="ellipsis">{m.text}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </aside>}
      </div>
    </>
  );
}

const fmtClock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function Density({ replay, span }: { replay: { vt: number }[]; span: number }) {
  const bins = useMemo(() => {
    const b = new Array(60).fill(0);
    for (const m of replay) b[Math.min(59, Math.floor((m.vt / span) * 60))]++;
    return b;
  }, [replay, span]);
  const mx = Math.max(1, ...bins);
  return <svg className="an-density" viewBox="0 0 60 20" preserveAspectRatio="none">{bins.map((v, i) => <rect key={i} x={i + 0.1} y={20 - (v / mx) * 20} width={0.8} height={(v / mx) * 20} />)}</svg>;
}

function NodeTip({ id, x, y, roster, status, node }: { id: string; x: number; y: number; roster: Roster; status?: AgentStatus; node?: GNode }) {
  const a = roster.agents.find((q) => q.callsign === id);
  const left = x + 280 > window.innerWidth ? x - 270 : x + 16;
  return (
    <div className="an-tip" style={{ left, top: y + 14 }}>
      {a ? (
        <>
          <div className="row" style={{ gap: 8 }}><b style={{ color: colorOf(roster, id) }}>{id}</b><span>{a.title}</span></div>
          <div className="xs muted">{roster.teams[a.team]?.name}</div>
          <div className="xs" style={{ marginTop: 4 }}>{a.duty}</div>
          <div className="xs faint" style={{ marginTop: 4 }}>{status?.state ?? "idle"}{status?.companies?.length ? ` · ${status.companies.join(", ")}` : ""}{status ? ` · ${status.sent} sent · ${status.received} received` : ""}</div>
          <div className="xs faint">Click to inspect · double-click for its channel · right-click for more</div>
        </>
      ) : (
        <><b>{node?.title}</b><div className="xs muted">{roster.sources[id]?.detail ?? "Output"}</div></>
      )}
    </div>
  );
}

function MiniMap({ L, nodes, view, stage, onJump, roster }: { L: ReturnType<typeof layout>; nodes: GNode[]; view: { x: number; y: number; k: number }; stage: React.RefObject<HTMLDivElement>; onJump: (x: number, y: number) => void; roster: Roster }) {
  const W = 160, H = Math.round((W * L.height) / L.width);
  const s = W / L.width;
  const el = stage.current;
  const vw = el ? el.clientWidth / view.k : 0, vh = el ? el.clientHeight / view.k : 0;
  const vx = -view.x / view.k, vy = -view.y / view.k;
  return (
    <div className="an-ov br an-mini" data-noexport onPointerDown={(e) => { e.stopPropagation(); const r = e.currentTarget.getBoundingClientRect(); onJump((e.clientX - r.left) / s, (e.clientY - r.top) / s); }}>
      <svg width={W} height={H}>
        {L.frames.map((f) => <rect key={f.team} x={f.x * s} y={f.y * s} width={f.w * s} height={f.h * s} rx={3} fill={roster.teams[f.team].color} opacity={0.12} />)}
        {nodes.map((n) => <rect key={n.id} x={n.x * s} y={n.y * s} width={Math.max(2, n.w * s)} height={Math.max(2, n.h * s)} rx={1.5} fill={n.kind === "agent" ? colorOf(roster, n.id) : "#9a9b9c"} opacity={0.8} />)}
        <rect x={vx * s} y={vy * s} width={vw * s} height={vh * s} className="vp" />
      </svg>
    </div>
  );
}

interface AutoStart { settings: { enabled: boolean; mode: "quick" | "full"; llm: boolean; skip_recent: number }; state: { last: number | null; reason: string | null } }

/** Auto-start settings and a "start now" button for the research workforce. */
function WorkforceControl({ active }: { active: boolean }) {
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
