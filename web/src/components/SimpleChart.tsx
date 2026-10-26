import { useId, useMemo, useRef, useState } from "react";
import { Bar } from "../lib/live";
import { isNum, num } from "../lib/format";
import { Level } from "./TradingChart";

/**
 * A quiet price chart for narrow panels: one area line of closes, a few
 * dashed reference levels and a hover read-out. No tools, no indicators -
 * the full TradingChart lives in Markets.
 */
export function SimpleChart({ bars, levels = [], height = 180, intraday, base }: {
  bars: Bar[];
  levels?: Level[];
  height?: number;
  intraday?: boolean;
  /** the line turns red below this (e.g. the previous close); defaults to the first close */
  base?: number | null;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const fillId = `sc-fill-${useId().replace(/:/g, "")}`;
  const [hover, setHover] = useState<number | null>(null);
  const pts = useMemo(() => bars.filter((b) => isNum(b.c)) as (Bar & { c: number })[], [bars]);
  const W = 1000, H = height, PAD = 6;
  const geo = useMemo(() => {
    if (pts.length < 2) return null;
    const ref0 = isNum(base) ? base : pts[0].c;
    // levels far outside the price range would flatten the line: keep only nearby ones
    const lo0 = Math.min(...pts.map((p) => p.c)), hi0 = Math.max(...pts.map((p) => p.c));
    const span0 = Math.max(hi0 - lo0, hi0 * 0.004);
    const near = levels.filter((l) => l.price > lo0 - span0 * 0.6 && l.price < hi0 + span0 * 0.6);
    const lo = Math.min(lo0, ...near.map((l) => l.price)), hi = Math.max(hi0, ...near.map((l) => l.price));
    const pad = (hi - lo) * 0.08 || hi * 0.01;
    const y = (v: number) => PAD + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - 2 * PAD);
    const x = (i: number) => (i / (pts.length - 1)) * W;
    const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.c).toFixed(1)}`).join("");
    const up = pts[pts.length - 1].c >= ref0;
    return { y, x, line, area: `${line}L${W},${H}L0,${H}Z`, up, near };
  }, [pts, levels, base, H]);

  if (!geo) return <div className="empty" style={{ height }}><span className="small">Not enough price data for this range.</span></div>;
  const color = geo.up ? "var(--up)" : "var(--down)";
  const h = hover != null ? pts[hover] : null;
  const fmtT = (t: number) => new Date(t * 1000).toLocaleString("en-IN", intraday ? { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "2-digit" });
  return (
    <div className="sc" style={{ height }}>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height={H}
        onPointerMove={(e) => { const r = ref.current!.getBoundingClientRect(); setHover(Math.max(0, Math.min(pts.length - 1, Math.round(((e.clientX - r.left) / r.width) * (pts.length - 1))))); }}
        onPointerLeave={() => setHover(null)}>
        <defs>
          <linearGradient id={fillId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity=".22" /><stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {geo.near.map((l) => <line key={l.title} x1={0} x2={W} y1={geo.y(l.price)} y2={geo.y(l.price)} stroke={l.color} strokeDasharray="6 6" strokeWidth={1.2} vectorEffect="non-scaling-stroke" opacity={0.8} />)}
        <path d={geo.area} fill={`url(#${fillId})`} />
        <path d={geo.line} fill="none" stroke={color} strokeWidth={1.8} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {hover != null && <line x1={geo.x(hover)} x2={geo.x(hover)} y1={0} y2={H} stroke="var(--fg-3)" strokeWidth={1} vectorEffect="non-scaling-stroke" />}
      </svg>
      {hover != null && <i className="sc-dot" style={{ left: `${(hover / (pts.length - 1)) * 100}%`, top: geo.y(pts[hover].c), background: color }} />}
      <div className="sc-levels">{geo.near.map((l) => <span key={l.title} style={{ top: geo.y(l.price), color: l.color }}>{l.title} {num(l.price, 0)}</span>)}</div>
      {h && <div className="sc-tip"><b>{num(h.c, 2)}</b><span>{fmtT(h.t)}</span></div>}
    </div>
  );
}
