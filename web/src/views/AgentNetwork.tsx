import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { AgentStatus, colorOf, dmId, Kind, KIND_META, Msg, roleName, Roster, useAgentRuns, useLiveFeed, useProfiles, useRoster, workforceSize } from "../lib/agents";
import { at, fmtClock, geom, Geom, GNode, layout, pathD, Pt, routes } from "../lib/agentGraph";
import { DEFAULT_LAYERS, Layers, Link, Mesh, Note, NOTE_TONES, posKey, Positions, uid, useStored, View } from "../lib/netPrefs";
import { LABEL_HEX } from "../lib/labels";
import { useTheme } from "../lib/theme";
import { BotGlyph } from "../components/AgentAvatar";
import { ExportButton } from "../components/ExportButton";
import { Density, MiniMap, NodeTip } from "../components/NetworkParts";
import { InspectorTab, NetworkInspector } from "../components/NetworkInspector";
import { EDGE_COLOR, LayersMenu, ViewsMenu } from "../components/NetworkLayers";
import { ResearchLauncher } from "../components/ResearchLauncher";
import { Icon, Popover, QueryView } from "../components/ui";
import { ago } from "../lib/format";
import { useApp } from "../components/workbenchContext";
import { Select } from "../components/Select";

interface Packet { g: Geom; t0: number; dur: number; el: SVGGElement; edge?: string; to: string; dir: Pt }
interface Spring { x: number; y: number; vx: number; vy: number }
type Tool = "select" | "pan" | "link" | "note" | "focus" | "erase";
const TOOLS: { id: Tool; icon: string; key: string; label: string; help: string }[] = [
  { id: "select", icon: "inspect", key: "V", label: "Select & move", help: "click an agent to inspect it, drag it to move it, drag on empty space to select several" },
  { id: "pan", icon: "move", key: "H", label: "Pan", help: "drag anywhere to move the view" },
  { id: "link", icon: "git-compare", key: "K", label: "Link", help: "drag from one node to another to draw your own connection" },
  { id: "note", icon: "note", key: "N", label: "Note", help: "click the map to pin a note" },
  { id: "focus", icon: "target", key: "G", label: "Focus", help: "click a node to show only it and its connections" },
  { id: "erase", icon: "eraser", key: "X", label: "Hide / delete", help: "click a node or edge to hide it, a link or note to delete it" },
];

// light theme: team colours are tuned for a dark canvas, so ink them darker
function ink(hex: string, light: boolean) {
  if (!light || !/^#[0-9a-f]{6}$/i.test(hex)) return hex;
  const n = parseInt(hex.slice(1), 16), f = 0.62;
  const c = (v: number) => Math.round(v * f).toString(16).padStart(2, "0");
  return `#${c(n >> 16)}${c((n >> 8) & 255)}${c(n & 255)}`;
}

export function AgentNetwork() {
  const roster = useRoster();
  return (
    <div className="net-page">
      <QueryView q={roster} rows={10}>{(r) => <Network roster={r} />}</QueryView>
    </div>
  );
}

function Network({ roster }: { roster: Roster }) {
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const app = useApp();
  const qc = useQueryClient();
  const light = useTheme() === "light";
  const runParam = params.get("run");
  const run = runParam ? Number(runParam) : null;
  const runs = useAgentRuns();
  const feed = useLiveFeed(run, 3000);
  const profiles = useProfiles();
  const live = !!feed.live?.active && !run;

  // ---------- what is shown
  const [layers, setLayers] = useStored<Layers>("net.layers.v2", DEFAULT_LAYERS);
  const [hidden, setHidden] = useStored<string[]>("net.hidden.v1", []);
  const [teamsOff, setTeamsOff] = useStored<string[]>("net.teamsOff.v1", []);
  const [kindsOff, setKindsOff] = useStored<Kind[]>("net.kindsOff.v1", []);
  const [mesh, setMesh] = useStored<Mesh>("net.mesh.v1", { links: [], notes: [] });
  const [views, setViews] = useStored<View[]>("net.views.v1", []);
  const [sideOpen, setSideOpen] = useStored<boolean>("net.side.v1", window.innerWidth >= 1400);
  const L = useMemo(() => layout(roster, layers.arrange, layers.detail), [roster, layers.arrange, layers.detail]);
  const pk = posKey(layers.arrange, layers.detail);
  const [pos, setPos] = useState<Positions>({});
  useEffect(() => { try { setPos(JSON.parse(localStorage.getItem(pk) || "{}")); } catch { setPos({}); } }, [pk]);
  const savePos = (p: Positions) => { try { localStorage.setItem(pk, JSON.stringify(p)); } catch { /* ignore */ } };
  const nodes = useMemo(() => L.nodes.map((n) => (pos[n.id] ? { ...n, ...pos[n.id] } : n)), [L, pos]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  const visible = useMemo(() => {
    const v = new Set<string>();
    for (const n of nodes) {
      if (hidden.includes(n.id)) continue;
      if (n.kind === "source" && !layers.sources) continue;
      if (n.kind === "output" && !layers.outputs) continue;
      if (n.role === "system" && !layers.ops) continue;
      if (n.role === "analyst" && !layers.analysts) continue;
      if (n.team && teamsOff.includes(n.team)) continue;
      v.add(n.id);
    }
    return v;
  }, [nodes, hidden, layers.sources, layers.outputs, layers.ops, layers.analysts, teamsOff]);
  /** where traffic for a node goes when the node itself is hidden: an analyst's lead */
  const proxy = useCallback((id: string) => {
    if (visible.has(id)) return id;
    const n = byId.get(id);
    if (n?.role === "analyst" && n.team && visible.has(`${n.team}-00`)) return `${n.team}-00`;
    return null;
  }, [visible, byId]);

  // ---------- interaction state
  const [tool, setTool] = useState<Tool>("select");
  const [view, setView] = useState({ x: 20, y: 10, k: 0.8 });
  // a mini-map click glides the map there; a drag follows the pointer without lag
  const [gliding, setGliding] = useState(false);
  const glideTimer = useRef<number>();
  const glideTo = (on: boolean) => {
    window.clearTimeout(glideTimer.current);
    setGliding(on);
    if (on) glideTimer.current = window.setTimeout(() => setGliding(false), 360);
  };
  const [sel, setSel] = useState<string | null>(params.get("focus"));
  const [selEdge, setSelEdge] = useState<string | null>(null);
  // several nodes picked with a selection box or Ctrl+click; they move and hide together
  const [multi, setMulti] = useState<Set<string>>(new Set());
  const [box, setBox] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [tab, setTab] = useState<InspectorTab>(params.get("focus") ? "agent" : "activity");
  const [agentTab, setAgentTab] = useState<"about" | "settings">("about");
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);
  const [edgeTip, setEdgeTip] = useState<{ id: string; x: number; y: number } | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; node: string | null; world: Pt } | null>(null);
  const [find, setFind] = useState("");
  const [editNote, setEditNote] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ from: string; to: Pt } | null>(null);
  // agents whose in-card dropdown (brief info) is open
  const [openInfo, setOpenInfo] = useState<string[]>([]);
  const toggleInfo = (id: string) => setOpenInfo((o) => (o.includes(id) ? o.filter((x) => x !== id) : [...o, id]));
  const stage = useRef<HTMLDivElement>(null);
  const [sw, setSw] = useState(1200);
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
      edgeCount.current.clear();
      if (wasLive.current && !run) {
        // a run that just finished live stays at its final state instead of restarting
        wasLive.current = false;
        const end = out.length ? out[out.length - 1].vt : 0;
        clock.current = end; cursor.current = out.length; setClockShow(end); setPlaying(false);
      } else { clock.current = 0; cursor.current = 0; setClockShow(0); setPlaying(true); }
    }).catch(() => undefined);
    return () => { stop = true; };
  }, [replayRun, live]); // eslint-disable-line react-hooks/exhaustive-deps
  const span = replay.length ? Math.max(1, replay[replay.length - 1].vt) : 1;

  // ---------- spawning info-bits
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
    let where: string | null = null, text = "", cls = "";
    if (m.kind === "verdict" && m.company) { where = "CMD-00"; text = `${m.company.replace(/ (Limited|Ltd\.?)$/i, "")} · ${String(d.label ?? "")}`; cls = "verdict"; }
    else if (m.kind === "finding" && typeof d.score === "number") { where = m.sender; text = `${d.score >= 0 ? "+" : ""}${d.score.toFixed(2)}`; cls = d.score >= 0 ? "pos" : "neg"; }
    else if (m.kind === "summary" && typeof d.score === "number") { where = m.sender; text = `Σ ${d.score >= 0 ? "+" : ""}${d.score.toFixed(2)}`; cls = "sum"; }
    else if (m.kind === "flag") { where = m.sender; text = "⚑ red flag"; cls = "neg"; }
    if (!where) return;
    const id = proxy(where);
    const n = id ? byId.get(id) : null;
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
    if (kindsOff.includes(m.kind) || !layer.current) return;
    if (layers.floats) floatFor(m);
    for (const [a0, b0] of routes(m)) {
      const a = proxy(a0), b = proxy(b0);
      if (!a || !b || a === b) continue;
      const A = byId.get(a), B = byId.get(b);
      if (!A || !B) continue;
      const edge = `${a}>${b}`;
      edgeCount.current.set(edge, (edgeCount.current.get(edge) ?? 0) + 1);
      pulse.current.set(a, performance.now());
      if (!layers.packets) { pulse.current.set(b, performance.now()); hot.current.set(edge, performance.now()); continue; }
      if (packets.current.length > 140) return;
      const color = KIND_META[m.kind]?.color ?? "#9cdcfe";
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("class", "pk");
      g.innerHTML = `<circle r="9" fill="${color}" opacity=".18"/><circle r="4.2" fill="${color}" stroke="${light ? "#0008" : "none"}" stroke-width="1"/><circle r="1.8" fill="#fff" opacity=".85"/>`;
      layer.current.appendChild(g);
      const dist = Math.hypot(B.x - A.x, B.y - A.y);
      const dir = { x: (B.x - A.x) / (dist || 1), y: (B.y - A.y) / (dist || 1) };
      packets.current.push({ g: geom(A, B), t0: performance.now(), dur: Math.min(1700, 520 + dist * 0.9), el: g, edge, to: b, dir });
      kick(a, -dir.x * 22, -dir.y * 22); // the sender recoils
    }
  }, [byId, kindsOff, proxy, layers.packets, layers.floats, light]); // eslint-disable-line react-hooks/exhaustive-deps

  // live: every new message becomes info-bits, staggered so bursts read as flow
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

  // the animation loop: replay clock, live queue, packets, edge glow, springs
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
          kick(p.to, p.dir.x * 60, p.dir.y * 60); // the receiver takes the hit
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
        el.style.setProperty("--hot", (h ? Math.max(0, 1 - (now - h) / 1400) : 0).toFixed(3));
        el.style.setProperty("--vol", Math.min(1, Math.log2(1 + (edgeCount.current.get(id) ?? 0)) / 7).toFixed(3));
      }
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
  // a new arrangement moves every node: drop the info-bits in flight
  useEffect(() => { packets.current.forEach((p) => p.el.remove()); packets.current = []; }, [L]);
  const seek = (s: number) => {
    packets.current.forEach((p) => p.el.remove());
    packets.current = [];
    clock.current = s;
    cursor.current = replay.findIndex((m) => m.vt > s);
    if (cursor.current < 0) cursor.current = replay.length;
    setClockShow(s);
  };

  // ---------- status (live from the run, or derived from the replay clock)
  const status: Record<string, AgentStatus> = useMemo(() => {
    if (live) return feed.live?.status ?? {};
    const out: Record<string, AgentStatus> = {};
    for (let i = 0; i < cursor.current; i++) {
      const m = replay[i];
      if (!m) continue;
      const s = out[m.sender] ?? (out[m.sender] = { state: "done", companies: [], task: "", since: m.ts, done: 0, errors: 0, sent: 0, received: 0, llm: 0 });
      s.sent++;
      if (m.kind === "finding" || (m.kind === "verdict" && m.company)) s.done++;
      for (const [, b] of routes(m)) {
        const r = out[b] ?? (out[b] = { state: "done", companies: [], task: "", since: m.ts, done: 0, errors: 0, sent: 0, received: 0, llm: 0 });
        r.received++;
      }
      if (clockShow - m.vt < 2.2 / Math.max(1, speed / 4)) { s.state = "working"; if (m.company && !s.companies.includes(m.company)) s.companies = [m.company]; }
    }
    return out;
  }, [live, feed.live?.status, clockShow, replay, speed]);

  const runNow = live ? feed.live?.run?.id : replayRun;
  const soFar = useMemo(() => (live ? feed.messages.filter((m) => m.run === runNow) : replay.slice(0, cursor.current)),
    [live, feed.messages, runNow, replay, clockShow]); // eslint-disable-line react-hooks/exhaustive-deps
  const tally = useMemo(() => {
    const c: Record<string, number> = {};
    let companies = 0, verdicts = 0, flags = 0, chat = 0;
    for (const m of soFar) {
      if (m.kind === "summary") c[`rep:${m.sender.slice(0, 3)}`] = (c[`rep:${m.sender.slice(0, 3)}`] ?? 0) + 1;
      if (m.kind === "fetch") { const s = String((m.data as Record<string, unknown>).source ?? ""); c[s] = (c[s] ?? 0) + 1; }
      if (m.channel !== "trace") chat++;
      if (m.kind === "task" && m.sender === "CMD-00") companies++;
      if (m.kind === "verdict" && m.company) verdicts++;
      if (m.kind === "flag") flags++;
    }
    const total = live ? (feed.live?.progress?.total ?? companies) : (replay.filter((m) => m.kind === "task" && m.sender === "CMD-00").length || companies);
    return { c, total: Math.max(total, verdicts), verdicts, flags, chat };
  }, [soFar, live, feed.live?.progress?.total, replay]);
  const latest = soFar.filter((m) => m.channel !== "trace").slice(-1)[0];

  // ---------- view: fit, zoom, pan
  const fit = useCallback(() => {
    const el = stage.current;
    if (!el) return;
    const vis = nodes.filter((n) => visible.has(n.id));
    if (!vis.length) return;
    const x0 = Math.min(...vis.map((n) => n.x)) - 30, y0 = Math.min(...vis.map((n) => n.y)) - 40;
    const x1 = Math.max(...vis.map((n) => n.x + n.w)) + 30, y1 = Math.max(...vis.map((n) => n.y + n.h)) + 40;
    const k = Math.min(1.4, Math.min((el.clientWidth - 40) / (x1 - x0), (el.clientHeight - 40) / (y1 - y0)));
    setView({ k, x: (el.clientWidth - (x1 - x0) * k) / 2 - x0 * k, y: (el.clientHeight - (y1 - y0) * k) / 2 - y0 * k });
  }, [nodes, visible]);
  const fitKey = `${layers.arrange}|${layers.detail}|${sideOpen}|${visible.size}`;
  useEffect(() => { const t = window.setTimeout(fit, 60); return () => window.clearTimeout(t); }, [fitKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSw(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const centreOn = useCallback((id: string) => {
    const n = byId.get(id), el = stage.current;
    if (!n || !el) return;
    const k = Math.max(view.k, 0.9);
    setView({ k, x: el.clientWidth / 2 - (n.x + n.w / 2) * k, y: el.clientHeight / 2 - (n.y + n.h / 2) * k });
    pulse.current.set(id, performance.now());
  }, [byId, view.k]);
  useEffect(() => { const f = params.get("focus"); if (f) { const t = window.setTimeout(() => centreOn(f), 160); return () => window.clearTimeout(t); } }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const zoomAt = (factor: number, cx?: number, cy?: number) => setView((v) => {
    const el = stage.current!;
    const px = cx ?? el.clientWidth / 2, py = cy ?? el.clientHeight / 2;
    const k = Math.max(0.25, Math.min(2.6, v.k * factor));
    return { k, x: px - ((px - v.x) * k) / v.k, y: py - ((py - v.y) * k) / v.k };
  });
  const toWorld = (cx: number, cy: number): Pt => {
    const r = stage.current!.getBoundingClientRect();
    return { x: (cx - r.left - view.x) / view.k, y: (cy - r.top - view.y) / view.k };
  };
  const inspect = (id: string, t: "about" | "settings" = "about") => {
    setSel(id); setSelEdge(null); setTab("agent"); setAgentTab(t); setSideOpen(true);
  };
  const pick = (cs: string) => { inspect(cs); if (visible.has(cs)) centreOn(cs); };
  const hide = (id: string) => {
    if (!hidden.includes(id)) setHidden([...hidden, id]);
    if (sel === id) setSel(null);
    if (focusId === id) setFocusId(null);
    app.toast(`${id.startsWith("E:") ? "Edge" : id} hidden - Layers › Hidden brings it back`);
  };
  const hideMany = (ids: string[]) => {
    setHidden([...hidden, ...ids.filter((x) => !hidden.includes(x))]);
    if (sel && ids.includes(sel)) setSel(null);
    if (focusId && ids.includes(focusId)) setFocusId(null);
    setMulti(new Set());
    app.toast(`${ids.length} hidden - Layers › Hidden brings them back`);
  };
  const addNote = (p: Pt) => {
    const n: Note = { id: uid(), x: p.x - 110, y: p.y - 24, text: "", arrange: layers.arrange, color: "amber", at: Date.now() };
    setMesh({ ...mesh, notes: [...mesh.notes, n] });
    setEditNote(n.id);
    setTool("select");
    if (!layers.annotations) setLayers({ ...layers, annotations: true });
  };

  // ---------- pointer: what a press does depends on the tool
  const drag = useRef<{ mode: "pan" | "node" | "note" | "box"; id?: string; sx: number; sy: number; ox: number; oy: number; moved: boolean;
    group?: Record<string, Pt>; base?: Set<string>; additive?: boolean } | null>(null);
  const onDown = (e: React.PointerEvent) => {
    // the middle button pans with any tool, like most canvas apps
    if (e.button === 1) {
      e.preventDefault();
      drag.current = { mode: "pan", sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y, moved: false };
      try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); } catch { /* the pointer is already gone */ }
      return;
    }
    if (e.button !== 0) return;
    setMenu(null);
    const t = e.target as HTMLElement;
    if (t.closest("textarea, input, button, [data-drop]")) return;
    const noteEl = t.closest("[data-note]") as HTMLElement | null;
    const nodeEl = t.closest("[data-node]") as HTMLElement | null;
    const panning = tool === "pan" || e.shiftKey;
    if (noteEl && !panning) {
      const id = noteEl.dataset.note!;
      if (tool === "erase") { setMesh({ ...mesh, notes: mesh.notes.filter((n) => n.id !== id) }); return; }
      const n = mesh.notes.find((x) => x.id === id)!;
      drag.current = { mode: "note", id, sx: e.clientX, sy: e.clientY, ox: n.x, oy: n.y, moved: false };
    } else if (nodeEl && !panning) {
      const id = nodeEl.dataset.node!;
      if (tool === "link") setDraft({ from: id, to: toWorld(e.clientX, e.clientY) });
      else if (tool === "focus") { setFocusId(focusId === id ? null : id); return; }
      else if (tool === "erase") { hide(id); return; }
      else if (tool === "note") { addNote(toWorld(e.clientX, e.clientY)); return; }
      else if (e.ctrlKey || e.metaKey) {
        // Ctrl+click adds or removes one node, like files on the desktop
        setMulti((m) => { const next = new Set(m); if (next.has(id)) next.delete(id); else next.add(id); return next; });
        return;
      } else {
        const n = byId.get(id)!;
        // dragging one of several selected nodes carries the whole group
        const group = multi.has(id) && multi.size > 1
          ? Object.fromEntries([...multi].map((m) => byId.get(m)).filter((g): g is GNode => !!g).map((g) => [g.id, { x: g.x, y: g.y }]))
          : undefined;
        if (!group && multi.size) setMulti(new Set());
        drag.current = { mode: "node", id, sx: e.clientX, sy: e.clientY, ox: n.x, oy: n.y, moved: false, group };
      }
    } else if (tool === "note" && !panning) {
      addNote(toWorld(e.clientX, e.clientY));
      return;
    } else if (tool === "select" && !panning) {
      // empty space with Select: draw a selection box (Ctrl keeps what is already picked)
      const additive = e.ctrlKey || e.metaKey;
      drag.current = { mode: "box", sx: e.clientX, sy: e.clientY, ox: 0, oy: 0, moved: false, base: additive ? new Set(multi) : new Set(), additive };
    } else {
      drag.current = { mode: "pan", sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y, moved: false };
    }
    try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); } catch { /* the pointer is already gone */ }
  };
  const onMove = (e: React.PointerEvent) => {
    if (draft) { setDraft({ ...draft, to: toWorld(e.clientX, e.clientY) }); return; }
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.sx, dy = e.clientY - d.sy;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    if (d.mode === "pan") setView((v) => ({ ...v, x: d.ox + dx, y: d.oy + dy }));
    else if (d.mode === "box" && d.moved) {
      const r = stage.current!.getBoundingClientRect();
      const b = { x0: Math.min(d.sx, e.clientX) - r.left, y0: Math.min(d.sy, e.clientY) - r.top, x1: Math.max(d.sx, e.clientX) - r.left, y1: Math.max(d.sy, e.clientY) - r.top };
      setBox(b);
      // every visible node the box touches, in world coordinates
      const w0 = (b.x0 - view.x) / view.k, h0 = (b.y0 - view.y) / view.k, w1 = (b.x1 - view.x) / view.k, h1 = (b.y1 - view.y) / view.k;
      const next = new Set(d.base);
      for (const n of nodes) {
        if (!visible.has(n.id) || n.x >= w1 || n.x + n.w <= w0 || n.y >= h1 || n.y + n.h <= h0) continue;
        if (d.additive && d.base!.has(n.id)) next.delete(n.id); else next.add(n.id);
      }
      setMulti((m) => (m.size === next.size && [...next].every((x) => m.has(x)) ? m : next));
    }
    else if (d.mode === "node" && d.moved && d.group) setPos((p) => ({ ...p, ...Object.fromEntries(Object.entries(d.group!).map(([id, o]) => [id, { x: o.x + dx / view.k, y: o.y + dy / view.k }])) }));
    else if (d.mode === "node" && d.moved) setPos((p) => ({ ...p, [d.id!]: { x: d.ox + dx / view.k, y: d.oy + dy / view.k } }));
    else if (d.mode === "note" && d.moved) setMesh((m) => ({ ...m, notes: m.notes.map((n) => (n.id === d.id ? { ...n, x: d.ox + dx / view.k, y: d.oy + dy / view.k } : n)) }));
  };
  const onUp = (e: React.PointerEvent) => {
    if (draft) {
      const under = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-node]") as HTMLElement | null;
      const to = under?.dataset.node;
      if (to && to !== draft.from && !mesh.links.some((l) => l.from === draft.from && l.to === to)) {
        const link: Link = { id: uid(), from: draft.from, to, label: "" };
        setMesh({ ...mesh, links: [...mesh.links, link] });
        setSelEdge(`L:${link.id}`); setSel(null); setTab("edge"); setSideOpen(true);
        if (!layers.annotations) setLayers({ ...layers, annotations: true });
      }
      setDraft(null);
      return;
    }
    const d = drag.current;
    drag.current = null;
    if (d?.mode === "node" && d.moved) setPos((p) => { savePos(p); return p; });
    if (d?.mode === "node" && !d.moved) inspect(d.id!);
    if (d?.mode === "note" && !d.moved) setEditNote(d.id!);
    if (d?.mode === "box") {
      setBox(null);
      if (!d.moved && !d.additive) { setMulti(new Set()); setSel(null); setSelEdge(null); setTab("activity"); }
    }
    if (d?.mode === "pan" && !d.moved && tool !== "pan") { setMulti(new Set()); setSel(null); setSelEdge(null); setTab("activity"); if (tool === "focus") setFocusId(null); }
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
      const tg = e.target instanceof Element ? e.target : null;
      if (tg?.closest("input, textarea, select, [contenteditable]")) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a" && tool === "select") { e.preventDefault(); setMulti(new Set(nodes.filter((n) => visible.has(n.id)).map((n) => n.id))); return; }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const t = TOOLS.find((x) => x.key.toLowerCase() === e.key.toLowerCase());
      if (t) { setTool(t.id); return; }
      if (e.key === "f" || e.key === "F") fit();
      else if (e.key === "+" || e.key === "=") zoomAt(1.2);
      else if (e.key === "-") zoomAt(1 / 1.2);
      else if (e.key === " " && !live) { e.preventDefault(); setPlaying((p) => !p); }
      else if (e.key === "i" || e.key === "I") setSideOpen((o) => !o);
      else if (e.key === "m" || e.key === "M") setLayers((l) => ({ ...l, minimap: !l.minimap }));
      else if (e.key === "Escape") { setMulti(new Set()); setSel(null); setSelEdge(null); setMenu(null); setFocusId(null); setDraft(null); setEditNote(null); setOpenInfo([]); setTab("activity"); setTool("select"); }
      else if ((e.key === "Delete" || e.key === "Backspace") && multi.size > 0) hideMany([...multi]);
      else if ((e.key === "Delete" || e.key === "Backspace") && selEdge?.startsWith("L:")) { setMesh((m) => ({ ...m, links: m.links.filter((l) => `L:${l.id}` !== selEdge) })); setSelEdge(null); setTab("activity"); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [fit, live, selEdge, multi, tool, nodes, visible]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!menu) return;
    const close = (e: PointerEvent) => { if (!(e.target instanceof Element && e.target.closest(".tc-menu"))) setMenu(null); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [menu]);

  // ---------- neighbourhoods: selection highlight and the focus tool
  const neighbours = useCallback((id: string) => {
    const s = new Set([id]);
    for (const e of L.edges) { if (e.from === id) s.add(e.to); if (e.to === id) s.add(e.from); }
    for (const l of mesh.links) { if (l.from === id) s.add(l.to); if (l.to === id) s.add(l.from); }
    return s;
  }, [L.edges, mesh.links]);
  const neigh = useMemo(() => (sel ? neighbours(sel) : null), [sel, neighbours]);
  const focusSet = useMemo(() => (focusId ? neighbours(focusId) : null), [focusId, neighbours]);
  const q = find.trim().toLowerCase();
  const searchHits = q ? nodes.filter((n) => (n.id + " " + n.title).toLowerCase().includes(q)) : [];
  const now = performance.now();
  const runInfo = feed.live?.run;
  const size = workforceSize(roster);
  const tc = (id: string) => ink(colorOf(roster, id), light);

  // ---------- context menus
  const toggleInRuns = async (cs: string, on: boolean) => {
    try {
      await api.put(`/api/agents/profiles/${cs}`, { enabled: on });
      await qc.invalidateQueries({ queryKey: ["agent-profiles"] });
      app.toast(on ? `${cs} takes part in runs again` : `${cs} sits out research runs from the next run`, "ok");
    } catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); }
  };
  const nodeMenu = (id: string, world: Pt) => {
    const a = roster.agents.find((x) => x.callsign === id);
    const team = a ? roster.teams[a.team] : null;
    const prof = profiles.data?.profiles[id];
    const close = () => setMenu(null);
    return (
      <>
        <div className="tc-mh">{id} · {byId.get(id)?.title}</div>
        <button onClick={() => { inspect(id); close(); }}><Icon name="info" className="sm" />Inspect</button>
        {a && a.role !== "system" && <button onClick={() => { inspect(id, "settings"); close(); }}><Icon name="settings-gear" className="sm" />Settings…</button>}
        <button onClick={() => { centreOn(id); close(); }}><Icon name="screen-normal" className="sm" />Centre on it</button>
        <button onClick={() => { setFocusId(id); close(); }}><Icon name="target" className="sm" />Focus on its connections</button>
        <button onClick={() => { setDraft({ from: id, to: world }); close(); }}><Icon name="git-compare" className="sm" />Draw a link from here</button>
        <hr />
        {team && <button onClick={() => nav(`/agents/chat?c=${team.channel}`)}><Icon name="comment-discussion" className="sm" />Open #{team.slug}</button>}
        {a && a.role !== "system" && <button onClick={() => nav(`/agents/chat?c=${encodeURIComponent(dmId(id, "YOU"))}`)}><Icon name="comment" className="sm" />Message {id}</button>}
        {a?.role === "analyst" && prof && <button onClick={() => { toggleInRuns(id, !prof.enabled); close(); }}><Icon name={prof.enabled ? "debug-pause" : "debug-start"} className="sm" />{prof.enabled ? "Leave out of research runs" : "Bring back into research runs"}</button>}
        <hr />
        <button onClick={() => { hide(id); close(); }}><Icon name="eye-closed" className="sm" />Hide on the map</button>
        {a && a.team !== "CMD" && a.team !== "OPS" && <button onClick={() => { setTeamsOff(Object.keys(roster.teams).filter((t) => t !== a.team && t !== "CMD" && t !== "OPS")); close(); }}><Icon name="filter" className="sm" />Show only {a.team}</button>}
        <button onClick={() => { navigator.clipboard?.writeText(id); close(); app.toast(`Copied ${id}`); }}><Icon name="copy" className="sm" />Copy callsign</button>
        {pos[id] && <button onClick={() => { const n = { ...pos }; delete n[id]; setPos(n); savePos(n); close(); }}><Icon name="discard" className="sm" />Reset its position</button>}
      </>
    );
  };
  const canvasMenu = (world: Pt) => (
    <>
      <div className="tc-mh">Agent Network</div>
      <button onClick={() => { addNote(world); setMenu(null); }}><Icon name="note" className="sm" />Add a note here</button>
      <button onClick={() => { fit(); setMenu(null); }}><Icon name="screen-normal" className="sm" />Fit to screen <kbd>F</kbd></button>
      {!live && <button onClick={() => { setPlaying(!playing); setMenu(null); }}><Icon name={playing ? "debug-pause" : "play"} className="sm" />{playing ? "Pause replay" : "Play replay"} <kbd>Space</kbd></button>}
      <hr />
      {(hidden.length > 0 || teamsOff.length > 0) && <button onClick={() => { setHidden([]); setTeamsOff([]); setMenu(null); }}><Icon name="eye" className="sm" />Show everything hidden ({hidden.length + teamsOff.length})</button>}
      {focusId && <button onClick={() => { setFocusId(null); setMenu(null); }}><Icon name="clear-all" className="sm" />Leave focus</button>}
      <button onClick={() => { setPos({}); savePos({}); setMenu(null); }}><Icon name="discard" className="sm" />Reset node positions</button>
    </>
  );

  // ---------- your link, in the inspector
  const link = selEdge?.startsWith("L:") ? mesh.links.find((l) => `L:${l.id}` === selEdge) : null;
  const linkEditor = link ? (
    <div className="col" style={{ gap: 10 }}>
      <div className="label">Your link</div>
      <b>{link.from} → {link.to}</b>
      <label className="fld"><span>Caption</span>
        <input className="inp sm" value={link.label} placeholder="e.g. should share filings" autoFocus
          onChange={(e) => setMesh({ ...mesh, links: mesh.links.map((l) => (l.id === link.id ? { ...l, label: e.target.value } : l)) })} /></label>
      <span className="xs faint">Links and notes are your own annotations on the map: they help you plan and explain the mesh, and stay in this browser. To change how agents actually work, use an agent's Settings.</span>
      <div className="row">
        <button className="btn sm sec" onClick={() => setMesh({ ...mesh, links: mesh.links.map((l) => (l.id === link.id ? { ...l, from: l.to, to: l.from } : l)) })}><Icon name="arrow-swap" className="xs" />Reverse</button>
        <button className="btn sm ghost" onClick={() => { setMesh({ ...mesh, links: mesh.links.filter((l) => l.id !== link.id) }); setSelEdge(null); setTab("activity"); }}><Icon name="trash" className="xs" />Delete</button>
      </div>
    </div>
  ) : undefined;

  const applyView = (v: View) => { setLayers({ ...DEFAULT_LAYERS, ...v.layers, edges: { ...DEFAULT_LAYERS.edges, ...v.layers.edges } }); setHidden(v.hidden); setTeamsOff(v.teamsOff); setFocusId(null); };
  const notesHere = layers.annotations ? mesh.notes.filter((n) => n.arrange === layers.arrange) : [];
  const toolNow = TOOLS.find((t) => t.id === tool)!;

  return (
    <div className={`net ${light ? "light" : ""}`}>
      <header className="net-top">
        <div className="net-title">
          <Icon name="type-hierarchy" />
          <b>Agent Network</b>
          <span className={`live-dot ${live ? "on" : ""}`}>{live ? "Live" : "Replay"}</span>
        </div>
        <Select size="sm" value={run == null ? "" : String(run)} title="Which run to show" ariaLabel="Which run to show" style={{ maxWidth: 220 }} menuWidth={260}
          onChange={(v) => { const p = new URLSearchParams(params); if (v) p.set("run", v); else p.delete("run"); setParams(p, { replace: true }); }}
          options={[{ value: "", label: `${feed.live?.active ? "Live run" : "Latest run"}${runInfo ? ` (#${runInfo.id})` : ""}` },
            ...(runs.data ?? []).map((r) => ({ value: String(r.id), label: `#${r.id} · ${r.mode}`, hint: r.started?.slice(5, 16).replace("T", " ") }))]} />
        <div className="net-find">
          <div className="search sm"><Icon name="search" /><input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find an agent"
            onKeyDown={(e) => { if (e.key === "Enter" && searchHits[0]) { pick(searchHits[0].id); setFind(""); } else if (e.key === "Escape") setFind(""); }} /></div>
          {searchHits.length > 0 && (
            <div className="net-hits">
              {searchHits.slice(0, 8).map((n) => (
                <button key={n.id} onClick={() => { pick(n.id); setFind(""); }}>
                  <i style={{ background: n.kind === "agent" ? colorOf(roster, n.id) : "var(--fg-3)" }} /><b>{n.id}</b><span className="ellipsis">{n.title}</span>
                  {!visible.has(n.id) && <span className="xs faint">hidden</span>}
                </button>
              ))}
            </div>
          )}
        </div>
        <span className="spacer" />
        <ViewsMenu views={views} setViews={setViews} current={{ layers, hidden, teamsOff }} apply={applyView} />
        <LayersMenu layers={layers} setLayers={setLayers} roster={roster} teamsOff={teamsOff} setTeamsOff={setTeamsOff} hidden={hidden} setHidden={setHidden}
          kindsOff={kindsOff} setKindsOff={setKindsOff} annotations={mesh.links.length + mesh.notes.length}
          clearAnnotations={() => setMesh({ links: [], notes: [] })} titleOf={(id) => byId.get(id)?.title ?? ""} />
        {!feed.live?.active && <ResearchLauncher small secondary />}
        <ExportButton title="Agent Network" target={stage} className="net-btn icon" />
        <Popover className="pop net-pop sm" trigger={(open, toggle) => <button className={`net-btn icon ${open ? "on" : ""}`} onClick={toggle} title="Shortcuts"><Icon name="keyboard" className="sm" /></button>}>
          {() => (
            <div className="nl keys">
              {TOOLS.map((t) => <div key={t.id}><kbd>{t.key}</kbd><span>{t.label} - {t.help}</span></div>)}
              <div><kbd>F</kbd><span>Fit the map to the screen</span></div>
              <div><kbd>+</kbd><span>Zoom in · <kbd>-</kbd> out (or the mouse wheel)</span></div>
              <div><kbd>Drag</kbd><span>on empty space draws a selection box · <kbd>Ctrl</kbd> adds to it</span></div>
              <div><kbd>Ctrl</kbd><span>+ click picks several · <kbd>Ctrl A</kbd> picks every node</span></div>
              <div><kbd>Shift</kbd><span>+ drag (or the middle button) pans with any tool</span></div>
              <div><kbd>Space</kbd><span>Play / pause the replay</span></div>
              <div><kbd>I</kbd><span>Inspector · <kbd>M</kbd> mini-map</span></div>
              <div><kbd>Esc</kbd><span>Clear selection and focus</span></div>
              <div><kbd>Del</kbd><span>Hide the selected nodes, or delete the selected link</span></div>
            </div>
          )}
        </Popover>
        <button className={`net-btn icon ${sideOpen ? "on" : ""}`} onClick={() => setSideOpen(!sideOpen)} title="Inspector (I)"><Icon name="layout-sidebar-right" className="sm" /></button>
      </header>

      <div className={`net-body ${sideOpen ? "" : "noside"}`}>
        <nav className="net-rail" aria-label="Map tools">
          {TOOLS.map((t) => (
            <button key={t.id} className={tool === t.id ? "on" : ""} onClick={() => setTool(t.id)} title={`${t.label} (${t.key}) - ${t.help}`}><Icon name={t.icon} /></button>
          ))}
          <i className="sep" />
          <button onClick={fit} title="Fit (F)"><Icon name="screen-normal" /></button>
          <button onClick={() => zoomAt(1.2)} title="Zoom in (+)"><Icon name="zoom-in" /></button>
          <button onClick={() => zoomAt(1 / 1.2)} title="Zoom out (-)"><Icon name="zoom-out" /></button>
          <button className={layers.minimap ? "on" : ""} onClick={() => setLayers({ ...layers, minimap: !layers.minimap })} title="Mini-map (M)"><Icon name="map" /></button>
        </nav>

        <div className={`an-stage net-stage tool-${tool}`} ref={stage} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onWheel={onWheel}
          onContextMenu={(e) => { e.preventDefault(); const n = (e.target as HTMLElement).closest("[data-node]") as HTMLElement | null; setMenu({ x: e.clientX, y: e.clientY, node: n?.dataset.node ?? null, world: toWorld(e.clientX, e.clientY) }); }}>
          <div className={`an-world ${gliding ? "glide" : ""}`} style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`, width: L.width, height: L.height }}>
            {layers.frames && layers.arrange === "hierarchy" && L.frames.filter((f) => !teamsOff.includes(f.team)).map((f) => {
              const t = roster.teams[f.team];
              const busy = roster.agents.filter((a) => a.team === f.team && status[a.callsign]?.state === "working").length;
              const far = !!focusSet && !roster.agents.some((a) => a.team === f.team && focusSet.has(a.callsign));
              return (
                <div key={f.team} className={`an-frame ${far ? "dim" : ""}`} style={{ left: f.x, top: f.y, width: f.w, height: f.h, ["--tc" as string]: tc(`${f.team}-00`) }}>
                  <span className="an-frame-h"><b>{f.team}</b> {t.name}{busy > 0 && <em>{busy} working</em>}</span>
                  <i className="an-frame-bar" style={{ width: `${Math.min(100, (100 * (tally.c[`rep:${f.team}`] ?? 0)) / Math.max(1, tally.total))}%` }} />
                </div>
              );
            })}
            <svg className="an-svg" width={L.width} height={L.height}>
              <defs>
                <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
                <marker id="net-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--accent-2)" /></marker>
              </defs>
              {L.edges.map((e) => {
                if (!layers.edges[e.kind] || !visible.has(e.from) || !visible.has(e.to) || hidden.includes(`E:${e.id}`)) return null;
                if (focusSet && !(e.from === focusId || e.to === focusId)) return null;
                const a = byId.get(e.from)!, b = byId.get(e.to)!;
                const dim = neigh && !(neigh.has(e.from) && neigh.has(e.to));
                const color = ink(e.kind === "report" || e.kind === "command" ? colorOf(roster, e.from) : EDGE_COLOR[e.kind], light);
                const g = geom(a, b);
                const mid = at(g, 0.5);
                return (
                  <g key={e.id} ref={(el) => { if (el) edgeEls.current.set(e.id, el); else edgeEls.current.delete(e.id); }}
                    className={`an-edge k-${e.kind} ${dim ? "dim" : ""} ${selEdge === e.id ? "sel" : ""}`} style={{ ["--ec" as string]: color }}>
                    <path d={pathD(g)} className="line" />
                    <path d={pathD(g)} className="flow" />
                    <path d={pathD(g)} className="hit" onPointerEnter={(ev) => setEdgeTip({ id: e.id, x: ev.clientX, y: ev.clientY })} onPointerLeave={() => setEdgeTip(null)}
                      onPointerDown={(ev) => { if (tool === "pan" || ev.shiftKey || ev.button !== 0) return; ev.stopPropagation(); if (tool === "erase") { hide(`E:${e.id}`); return; } setSelEdge(e.id); setSel(null); setTab("edge"); setSideOpen(true); }} />
                    {layers.labels && <text x={mid.x} y={mid.y - 6} className="an-elabel">{e.kind === "command" ? "team report" : e.kind === "consume" ? "cross-team read" : e.kind === "input" ? "feed" : e.kind === "report" ? "finding" : e.kind === "output" ? "verdict" : "control"}</text>}
                  </g>
                );
              })}
              {layers.annotations && mesh.links.map((l) => {
                const a = byId.get(l.from), b = byId.get(l.to);
                if (!a || !b || !visible.has(l.from) || !visible.has(l.to)) return null;
                if (focusSet && !(focusSet.has(l.from) && focusSet.has(l.to))) return null;
                const g = geom(a, b);
                const mid = at(g, 0.5);
                return (
                  <g key={l.id} className={`an-edge k-custom ${selEdge === `L:${l.id}` ? "sel" : ""}`}>
                    <path d={pathD(g)} className="line" markerEnd="url(#net-arrow)" />
                    <path d={pathD(g)} className="hit" onPointerDown={(ev) => {
                      if (tool === "pan" || ev.shiftKey || ev.button !== 0) return;
                      ev.stopPropagation();
                      if (tool === "erase") { setMesh({ ...mesh, links: mesh.links.filter((x) => x.id !== l.id) }); return; }
                      setSelEdge(`L:${l.id}`); setSel(null); setTab("edge"); setSideOpen(true);
                    }} />
                    {l.label && <text x={mid.x} y={mid.y - 7} className="an-elabel custom">{l.label}</text>}
                  </g>
                );
              })}
              {draft && byId.get(draft.from) && (() => { const A = byId.get(draft.from)!; return <line x1={A.x + A.w / 2} y1={A.y + A.h / 2} x2={draft.to.x} y2={draft.to.y} className="an-draft" markerEnd="url(#net-arrow)" />; })()}
              <g ref={layer} filter="url(#glow)" />
            </svg>
            <div className="an-floats" ref={floats} />
            {nodes.map((n) => {
              if (!visible.has(n.id)) return null;
              const st = status[n.id];
              const isSel = sel === n.id || multi.has(n.id);
              const far = !!focusSet && !focusSet.has(n.id);
              const dim = (neigh && !neigh.has(n.id)) || (searchHits.length > 0 && !searchHits.includes(n));
              const color = n.kind === "source" ? ink("#57a3f8", light) : n.kind === "output" ? ink("#e0b97f", light) : tc(n.id);
              const p = pulse.current.get(n.id);
              const pulsing = p && now - p < 700;
              const off = n.role === "analyst" && profiles.data?.profiles[n.id]?.enabled === false;
              const common = {
                "data-node": n.id,
                ref: (el: HTMLDivElement | null) => { if (el) nodeEls.current.set(n.id, el); else nodeEls.current.delete(n.id); },
                style: { left: n.x, top: n.y, width: n.w, height: n.h, ["--tc" as string]: color },
                onPointerEnter: (e: React.PointerEvent) => setHover({ id: n.id, x: e.clientX, y: e.clientY }),
                onPointerMove: (e: React.PointerEvent) => setHover({ id: n.id, x: e.clientX, y: e.clientY }),
                onPointerLeave: () => setHover(null),
              };
              if (n.kind !== "agent") {
                const v = n.id === "OUT-VERDICT" ? tally.verdicts : n.id === "OUT-ALERTS" ? tally.flags : n.id === "OUT-ROOM" ? tally.chat : tally.c[n.id] ?? 0;
                return (
                  <div key={n.id} {...common} className={`an-node round ${far ? "far" : ""} ${dim ? "dim" : ""} ${isSel ? "sel" : ""} ${pulsing ? "pulse" : ""}`}>
                    <Icon name={n.icon ?? "circle"} />
                    {v > 0 && <span key={v} className="an-count bump">{v}</span>}
                    <span className="an-cap">{n.title}</span>
                  </div>
                );
              }
              const state = st?.state ?? "idle";
              const compact = layers.detail === "compact";
              return (
                <div key={n.id} {...common} className={`an-node card ${compact ? "compact" : ""} r-${n.role} s-${state} ${off ? "off" : ""} ${far ? "far" : ""} ${dim ? "dim" : ""} ${isSel ? "sel" : ""} ${pulsing ? "pulse" : ""}`}
                  onDoubleClick={() => { if (tool === "select" && n.role !== "system") nav(`/agents/chat?c=${encodeURIComponent(dmId(n.id, "YOU"))}`); }}>
                  <div className="an-top">
                    <span className="an-ic"><BotGlyph role={n.role ?? "analyst"} size={n.role === "chief" ? (compact ? 18 : 22) : compact ? 14 : 17} color={color} />
                      {n.role === "chief" && tally.total > 0 && (
                        <svg className="an-ring" viewBox="0 0 44 44"><circle cx="22" cy="22" r="19" className="bg" />
                          <circle cx="22" cy="22" r="19" className="fg" style={{ strokeDasharray: `${(119.4 * tally.verdicts) / tally.total} 119.4` }} /></svg>
                      )}
                    </span>
                    <div className="an-id"><b>{n.id}</b><span>{compact && n.role === "analyst" ? n.title.replace(/ Analyst$/, "") : roleName(n.role ?? "analyst")}</span></div>
                    <span className={`an-state s-${off ? "off" : state}`} title={off ? "left out of runs" : state} />
                    <button className={`an-more ${openInfo.includes(n.id) ? "on" : ""}`} onClick={(e) => { e.stopPropagation(); toggleInfo(n.id); }}
                      title={openInfo.includes(n.id) ? "Hide details" : "Show details"} aria-expanded={openInfo.includes(n.id)}>
                      <Icon name={openInfo.includes(n.id) ? "chevron-up" : "chevron-down"} />
                    </button>
                  </div>
                  {!compact && <>
                    <div className="an-title">{n.title.replace(/ Analyst$/, "")}</div>
                    <div className="an-task">
                      <span className="grow ellipsis">{off ? "left out of runs" : state === "working" ? <><span className="spin-ring" />{st?.companies?.[0]?.replace(/ Limited$/i, "") ?? "working"}</> : state === "error" ? "error" : n.role === "chief" && tally.total ? `${tally.verdicts}/${tally.total} verdicts` : st?.done ? `${st.done} done` : "idle"}</span>
                      {st && (st.sent > 0 || st.received > 0) && <span className="an-io"><b key={`s${st.sent}`} className="bump">↑{st.sent}</b><b key={`r${st.received}`} className="bump">↓{st.received}</b></span>}
                    </div>
                  </>}
                </div>
              );
            })}
            {openInfo.filter((id) => visible.has(id)).map((id) => {
              const n = byId.get(id)!;
              const a = roster.agents.find((x) => x.callsign === id);
              if (!a) return null;
              const st = status[id];
              const prof = profiles.data?.profiles[id];
              const off = a.role === "analyst" && prof?.enabled === false;
              const state = off ? "left out of runs" : st?.state === "working" ? `working on ${st.companies?.[0] ?? "…"}` : st?.state ?? "idle";
              const tuned = prof ? [prof.stance !== "balanced" && prof.stance, prof.weight !== 1 && `weight x${prof.weight}`, prof.llm !== "auto" && `AI ${prof.llm}`, prof.instructions && "has instructions"].filter(Boolean) : [];
              return (
                <div key={`d-${id}`} data-drop className="an-drop" style={{ left: n.x, top: n.y + n.h + 8, width: Math.max(n.w, 250), ["--tc" as string]: tc(id) }}>
                  <div className="an-drop-h"><b>{id}</b><span>{a.title}</span>
                    <button onClick={() => toggleInfo(id)} title="Close"><Icon name="close" className="xs" /></button></div>
                  <div className="an-drop-team">{roster.teams[a.team]?.name} · {roleName(a.role)}</div>
                  <div className={`an-drop-state s-${off ? "off" : st?.state ?? "idle"}`}><i />{state}</div>
                  {st && <div className="an-drop-stats"><span><b>{st.done}</b> done</span><span><b>{st.sent}</b> sent</span><span><b>{st.received}</b> received</span>{st.llm > 0 && <span><b>{st.llm}</b> AI-assisted</span>}</div>}
                  <p>{a.duty}</p>
                  {tuned.length > 0 && <div className="an-drop-tuned">Tuned: {tuned.join(" · ")}</div>}
                  <div className="an-drop-acts">
                    <button onClick={() => inspect(id)} title="Inspect"><Icon name="info" className="xs" /><span>Inspect</span></button>
                    {a.role !== "system" && <button onClick={() => nav(`/agents/chat?c=${encodeURIComponent(dmId(id, "YOU"))}`)}><Icon name="comment" className="xs" /><span>Message</span></button>}
                    {a.role !== "system" && <button onClick={() => inspect(id, "settings")} title="Settings"><Icon name="settings-gear" className="xs" /><span>Settings</span></button>}
                  </div>
                </div>
              );
            })}
            {notesHere.map((n) => {
              const editing = editNote === n.id;
              const tone = NOTE_TONES.find((t) => t.id === n.color) ?? NOTE_TONES[0];
              const update = (patch: Partial<Note>) => setMesh((m) => ({ ...m, notes: m.notes.map((x) => (x.id === n.id ? { ...x, ...patch, at: Date.now() } : x)) }));
              const remove = () => { setMesh((m) => ({ ...m, notes: m.notes.filter((x) => x.id !== n.id) })); setEditNote(null); };
              // finishing an empty note throws it away
              const finish = () => { setEditNote(null); if (!n.text.trim()) remove(); };
              return (
                <div key={n.id} data-note={n.id} className={`an-note ${editing ? "editing" : ""}`} style={{ left: n.x, top: n.y, ["--nt" as string]: tone.c }}
                  onDoubleClick={() => setEditNote(n.id)} onBlur={(e) => { if (editing && !e.currentTarget.contains(e.relatedTarget as Node)) finish(); }}>
                  <div className="an-note-h">
                    <Icon name="gripper" className="xs an-note-grip" />
                    <span className="an-note-t">Note</span>
                    {editing ? (
                      <span className="an-note-tones" role="radiogroup" aria-label="Note colour">
                        {NOTE_TONES.map((t) => <button key={t.id} role="radio" aria-checked={t.id === tone.id} aria-label={t.label} title={t.label} className={t.id === tone.id ? "on" : ""} style={{ background: t.c }} onClick={() => update({ color: t.id })} />)}
                      </span>
                    ) : <span className="an-note-when">{n.at ? ago(n.at / 1000) : ""}</span>}
                    {!editing && <button className="an-note-x" onClick={() => setEditNote(n.id)} title="Edit"><Icon name="edit" className="xs" /></button>}
                    <button className="an-note-x" onClick={remove} title="Delete this note"><Icon name="trash" className="xs" /></button>
                  </div>
                  {editing ? (
                    <>
                      <textarea autoFocus value={n.text} placeholder="What should you remember about this part of the network?" maxLength={600}
                        rows={Math.min(10, Math.max(3, n.text.split("\n").length + 1))}
                        onChange={(e) => update({ text: e.target.value })}
                        onKeyDown={(e) => { if (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey))) { e.preventDefault(); e.stopPropagation(); finish(); } }} />
                      <div className="an-note-f"><span>{n.text.length}/600 · <kbd>Ctrl</kbd>+<kbd>Enter</kbd> to finish</span><button className="an-note-done" onClick={finish}>Done</button></div>
                    </>
                  ) : <div className="an-note-b">{n.text || <span className="faint">Empty — double-click to write</span>}</div>}
                </div>
              );
            })}
          </div>

          {focusId && (
            <div className="net-chip" data-noexport onPointerDown={(e) => e.stopPropagation()}>
              <span className="net-chip-ic"><Icon name="target" /></span><span className="net-chip-t">Focused on <b>{focusId}</b></span><button onClick={() => setFocusId(null)} title="Leave focus (Esc)"><Icon name="close" className="xs" /></button>
            </div>
          )}
          {box && <div className="an-marquee" style={{ left: box.x0, top: box.y0, width: box.x1 - box.x0, height: box.y1 - box.y0 }} />}
          {multi.size > 0 && !focusId && (
            <div className="net-chip sel" data-noexport onPointerDown={(e) => e.stopPropagation()}>
              <span className="net-chip-ic"><Icon name="checklist" /></span>
              <span className="net-chip-t"><b>{multi.size} selected</b> · drag one to move them all</span>
              {multi.size === 1 && <button onClick={() => inspect([...multi][0])} title="Inspect"><Icon name="info" className="xs" /></button>}
              <button onClick={() => hideMany([...multi])} title="Hide them (Del)"><Icon name="eye-closed" className="xs" /></button>
              <button onClick={() => setMulti(new Set())} title="Clear the selection (Esc)"><Icon name="close" className="xs" /></button>
            </div>
          )}
          {tool !== "select" && !focusId && multi.size === 0 && (
            <div className="net-chip tool" data-noexport onPointerDown={(e) => e.stopPropagation()}>
              <span className="net-chip-ic"><Icon name={toolNow.icon} /></span><span className="net-chip-t"><b>{toolNow.label}</b> · {toolNow.help}</span><button onClick={() => setTool("select")} title="Back to Select (V)"><Icon name="close" className="xs" /></button>
            </div>
          )}
          {layers.minimap && sw >= 600 && <MiniMap L={L} nodes={nodes.filter((n) => visible.has(n.id))} view={view} stage={stage} onJump={(x, y, smooth) => { const el = stage.current!; glideTo(smooth); setView((v) => ({ ...v, x: el.clientWidth / 2 - x * v.k, y: el.clientHeight / 2 - y * v.k })); }} roster={roster} gliding={gliding} />}
          {hover && !menu && !drag.current && !draft && <NodeTip id={hover.id} x={hover.x} y={hover.y} roster={roster} status={status[hover.id]} node={byId.get(hover.id)} />}
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
            <div className="tc-menu" style={{ left: Math.min(menu.x, window.innerWidth - 270), top: Math.min(menu.y, window.innerHeight - 420) }} onPointerDown={(e) => e.stopPropagation()}>
              {menu.node ? nodeMenu(menu.node, menu.world) : canvasMenu(menu.world)}
            </div>
          )}
        </div>

        {sideOpen && (
          <NetworkInspector roster={roster} tab={tab} setTab={setTab} sel={sel} selEdge={selEdge} status={status}
            seen={live ? feed.messages : replay.slice(0, cursor.current)} all={live ? feed.messages : replay}
            live={live} playing={playing} run={runInfo} runId={replayRun} prog={feed.live?.progress}
            nodeTitle={(id) => byId.get(id)?.title} onPick={pick} agentTab={agentTab} edgeView={linkEditor} onClose={() => setSideOpen(false)} />
        )}
      </div>

      <footer className="net-bot">
        {!live && replay.length > 0 ? (
          <div className="net-transport">
            <button className="ibtn" onClick={() => { if (!playing && cursor.current >= replay.length) seek(0); setPlaying(!playing); }} title="Play / pause (Space)"><Icon name={playing ? "debug-pause" : "play"} /></button>
            <span className="xs faint">Replay #{replayRun}</span>
            <Density replay={replay} span={span} />
            <input type="range" className="sl" min={0} max={span} step={0.1} value={clockShow} onChange={(e) => seek(Number(e.target.value))} aria-label="Replay position" />
            <span className="mono xs">{fmtClock(clockShow)} / {fmtClock(span)}</span>
            <Select size="sm" value={speed} onChange={setSpeed} ariaLabel="Replay speed" options={[1, 2, 4, 8, 16].map((s) => ({ value: s, label: `${s}×` }))} />
          </div>
        ) : (
          <div className="net-transport">
            <span className={`live-dot ${live ? "on" : ""}`}>{live ? `Live · run #${runInfo?.id}` : "No run to replay yet"}</span>
            {live && feed.live?.progress && <span className="xs faint">{feed.live.progress.done}/{feed.live.progress.total} companies</span>}
          </div>
        )}
        <div className="net-last" title={latest?.text}>
          {latest && <><i style={{ background: KIND_META[latest.kind]?.color }} /><b style={{ color: tc(latest.sender) }}>{latest.sender}</b>{latest.to && <span className="faint">→ {latest.to}</span>}<span className="ellipsis">{latest.text}</span></>}
        </div>
        <span className="xs faint net-count">{visible.size}/{L.nodes.length} nodes · {size.agents} agents</span>
        <span className="an-zoom">{Math.round(view.k * 100)}%</span>
      </footer>
    </div>
  );
}
