import { useMemo, useRef } from "react";
import { AgentStatus, colorOf, Roster } from "../lib/agents";
import { GNode, Layout } from "../lib/agentGraph";

export function Density({ replay, span }: { replay: { vt: number }[]; span: number }) {
  const bins = useMemo(() => {
    const b = new Array(60).fill(0);
    for (const m of replay) b[Math.min(59, Math.floor((m.vt / span) * 60))]++;
    return b;
  }, [replay, span]);
  const mx = Math.max(1, ...bins);
  return <svg className="an-density" viewBox="0 0 60 20" preserveAspectRatio="none">{bins.map((v, i) => <rect key={i} x={i + 0.1} y={20 - (v / mx) * 20} width={0.8} height={(v / mx) * 20} />)}</svg>;
}

export function NodeTip({ id, x, y, roster, status, node }: { id: string; x: number; y: number; roster: Roster; status?: AgentStatus; node?: GNode }) {
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
          <div className="xs faint">Click to inspect · double-click to message it · right-click for more</div>
        </>
      ) : (
        <><b>{node?.title}</b><div className="xs muted">{roster.sources[id]?.detail ?? "Output"}</div></>
      )}
    </div>
  );
}

/**
 * The whole map in miniature. Click to glide the view there; drag the
 * highlighted box (or anywhere) and the map follows the pointer live.
 */
export function MiniMap({ L, nodes, view, stage, onJump, roster, gliding }: { L: Layout; nodes: GNode[]; view: { x: number; y: number; k: number }; stage: React.RefObject<HTMLDivElement>; onJump: (x: number, y: number, smooth: boolean) => void; roster: Roster; gliding: boolean }) {
  const W = 160, H = Math.round((W * L.height) / L.width);
  const s = W / L.width;
  const el = stage.current;
  const vw = el ? el.clientWidth / view.k : 0, vh = el ? el.clientHeight / view.k : 0;
  const vx = -view.x / view.k, vy = -view.y / view.k;
  // while dragging: where in the box it was grabbed, so the box does not snap its centre to the pointer
  const grab = useRef<{ dx: number; dy: number } | null>(null);
  const at = (e: React.PointerEvent) => { const r = e.currentTarget.getBoundingClientRect(); return { x: (e.clientX - r.left) / s, y: (e.clientY - r.top) / s }; };
  const down = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    if (e.button !== 0) return;
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* not capturable */ }
    const p = at(e), cx = vx + vw / 2, cy = vy + vh / 2;
    const inside = p.x >= vx && p.x <= vx + vw && p.y >= vy && p.y <= vy + vh;
    if (inside) grab.current = { dx: p.x - cx, dy: p.y - cy };
    else { grab.current = { dx: 0, dy: 0 }; onJump(p.x, p.y, true); }
  };
  const move = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!grab.current) return;
    const p = at(e);
    onJump(Math.max(0, Math.min(L.width, p.x - grab.current.dx)), Math.max(0, Math.min(L.height, p.y - grab.current.dy)), false);
  };
  const up = (e: React.PointerEvent<HTMLDivElement>) => { grab.current = null; try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* already released */ } };
  return (
    <div className={`an-ov br an-mini ${grab.current ? "dragging" : ""}`} data-noexport onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
      <svg width={W} height={H}>
        {L.frames.map((f) => <rect key={f.team} x={f.x * s} y={f.y * s} width={f.w * s} height={f.h * s} rx={3} fill={roster.teams[f.team].color} opacity={0.12} />)}
        {nodes.map((n) => <rect key={n.id} x={n.x * s} y={n.y * s} width={Math.max(2, n.w * s)} height={Math.max(2, n.h * s)} rx={1.5} fill={n.kind === "agent" ? colorOf(roster, n.id) : "#9a9b9c"} opacity={0.8} />)}
        <rect x={0} y={0} width={vw * s} height={vh * s} className={`vp ${gliding ? "glide" : ""}`} style={{ transform: `translate(${vx * s}px, ${vy * s}px)` }} />
      </svg>
    </div>
  );
}
