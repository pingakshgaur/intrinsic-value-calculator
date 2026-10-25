import { isNum } from "../lib/format";

/** Inline SVG sparkline; green or red against `base` (default the first point). */
export function Spark({ values, base, width = 96, height = 28, fill = true }: { values: (number | null | undefined)[]; base?: number | null; width?: number; height?: number; fill?: boolean }) {
  const v = values.filter(isNum);
  if (v.length < 2) return <svg width={width} height={height} className="spark" aria-hidden />;
  const ref = isNum(base) ? base : v[0];
  const lo = Math.min(...v, ref), hi = Math.max(...v, ref);
  const span = hi - lo || 1;
  const x = (i: number) => (i / (v.length - 1)) * (width - 2) + 1;
  const y = (p: number) => height - 2 - ((p - lo) / span) * (height - 4);
  const pts = v.map((p, i) => `${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const col = v[v.length - 1] >= ref ? "var(--up)" : "var(--down)";
  return (
    <svg width={width} height={height} className="spark" aria-hidden>
      {isNum(base) && <line x1={0} x2={width} y1={y(ref)} y2={y(ref)} stroke="var(--c-lines)" strokeOpacity={0.5} strokeDasharray="2 3" />}
      {fill && <polygon points={`${x(0)},${height} ${pts} ${x(v.length - 1)},${height}`} fill={col} opacity={0.1} />}
      <polyline points={pts} fill="none" stroke={col} strokeWidth={1.4} strokeLinejoin="round" />
    </svg>
  );
}

/** Where `value` sits between `lo` and `hi` (day range, 52-week range). */
export function Position({ lo, hi, value, width = 90 }: { lo: number | null | undefined; hi: number | null | undefined; value: number | null | undefined; width?: number }) {
  if (!isNum(lo) || !isNum(hi) || !isNum(value) || hi <= lo) return <span className="faint">—</span>;
  const p = Math.max(0, Math.min(1, (value - lo) / (hi - lo)));
  return (
    <span className="posbar" style={{ width }} title={`${lo.toFixed(2)} – ${hi.toFixed(2)}`}>
      <i style={{ left: `calc(${p * 100}% - 1px)` }} />
    </span>
  );
}
