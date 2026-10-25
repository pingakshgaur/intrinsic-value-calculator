import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, Treemap, XAxis, YAxis, ZAxis } from "recharts";
import { HMResult, Verdict } from "../lib/api";
import { isNum, money, pct, shortName, titleCase } from "../lib/format";
import { HM_COLOR, LABEL_HEX, LENSES, LENS_COLOR, LENS_HINT, LENS_NAME } from "../lib/labels";

export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function niceTicks(min: number, max: number, n: number) {
  const span = max - min;
  if (span <= 0) return [min];
  const mag = Math.pow(10, Math.floor(Math.log10(span / n)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) ?? 10 * mag;
  const out: number[] = [];
  for (let t = Math.ceil(min / step) * step; t <= max; t += step) out.push(Math.round(t * 1e6) / 1e6);
  return out;
}

/* ------------------------------------------------------------------ range */
export function ValueRange({ r, ghost, height = 110 }: { r: HMResult; ghost?: HMResult | null; height?: number }) {
  const [box, width] = useWidth<HTMLDivElement>();
  const pts = [r.price, r.bear_value, r.bull_value, r.value, r.buy_below, r.low, r.high, ghost?.value].filter(isNum);
  return (
    <div ref={box} style={{ width: "100%" }}>
      {pts.length < 2 ? <div className="muted small">Not enough values to draw a range.</div> : width > 0 && <RangeSvg r={r} ghost={ghost} pts={pts} W={Math.max(200, width - 70)} height={height} />}
    </div>
  );
}

function RangeSvg({ r, ghost, pts, W, height }: { r: HMResult; ghost?: HMResult | null; pts: number[]; W: number; height: number }) {
  const lo = Math.min(...pts), hi = Math.max(...pts);
  const pad = (hi - lo) * 0.08 || hi * 0.1 || 1;
  const min = Math.max(0, lo - pad), max = hi + pad;
  const x = (v: number) => ((v - min) / (max - min)) * W;
  const ticks = niceTicks(min, max, Math.max(3, Math.min(8, Math.floor(W / 130))));
  const mark = (v: number | null | undefined, color: string, label: string, y: number, dashed = false) =>
    isNum(v) ? (
      <g>
        <line x1={x(v)} x2={x(v)} y1={24} y2={74} stroke={color} strokeWidth={2} strokeDasharray={dashed ? "4 3" : undefined} />
        <text x={x(v)} y={y} textAnchor="middle" fill={color} fontSize={10.5} fontWeight={600}>{label}</text>
        <text x={x(v)} y={y + 12} textAnchor="middle" fill="var(--fg-2)" fontSize={10} fontFamily="var(--mono)">{money(v, 0)}</text>
      </g>
    ) : null;
  return (
    <svg viewBox={`-35 0 ${W + 70} ${height}`} width={W + 70} height={height} style={{ overflow: "visible", display: "block" }}>
      <line x1={0} x2={W} y1={49} y2={49} stroke="var(--line)" />
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={44} y2={54} stroke="#3a3b3c" />
          <text x={x(t)} y={height - 2} textAnchor="middle" fill="var(--fg-3)" fontSize={9.5} fontFamily="var(--mono)">{money(t, 0)}</text>
        </g>
      ))}
      {isNum(r.low) && isNum(r.high) && <rect x={x(r.low)} y={57} width={Math.max(2, x(r.high) - x(r.low))} height={6} rx={3} fill={HM_COLOR} opacity={0.4}><title>P10–P90</title></rect>}
      {isNum(r.bear_value) && isNum(r.bull_value) && <rect x={x(r.bear_value)} y={38} width={Math.max(2, x(r.bull_value) - x(r.bear_value))} height={14} rx={3} fill="#57A3F8" opacity={0.2} stroke="#57A3F8" strokeOpacity={0.5}><title>Bear → bull</title></rect>}
      {isNum(ghost?.value) && <line x1={x(ghost!.value!)} x2={x(ghost!.value!)} y1={30} y2={70} stroke="var(--fg-3)" strokeWidth={2} strokeDasharray="2 3"><title>Saved: {money(ghost!.value)}</title></line>}
      {mark(r.buy_below, "#86CF86", "Buy-below", 11, true)}
      {mark(r.value, HM_COLOR, "HYBRID MODEL", 88)}
      {isNum(r.price) && (
        <g>
          <line x1={x(r.price)} x2={x(r.price)} y1={24} y2={74} stroke="#E0B97F" strokeWidth={2} />
          <polygon points={`${x(r.price)},37 ${x(r.price) + 6},49 ${x(r.price)},61 ${x(r.price) - 6},49`} fill="#E0B97F" />
          <text x={x(r.price)} y={11} textAnchor="middle" fill="#E0B97F" fontSize={10.5} fontWeight={600}>Price {money(r.price, 0)}</text>
        </g>
      )}
    </svg>
  );
}

export function RangeLegend({ ghost }: { ghost?: boolean }) {
  return (
    <div className="legend">
      <span><i style={{ background: "#E0B97F" }} />Price</span>
      <span><i style={{ background: HM_COLOR }} />HYBRID MODEL</span>
      <span><i style={{ background: "#57A3F838", outline: "1px solid #57A3F8" }} />Bear → bull</span>
      <span><i style={{ background: "#AD80D766" }} />P10–P90</span>
      <span><i style={{ background: "#86CF86" }} />Buy-below</span>
      {ghost && <span><i style={{ outline: "1px dashed var(--fg-3)" }} />Saved</span>}
    </div>
  );
}

/* ------------------------------------------------------------------ lens contribution */
/**
 * How far each lens pulls the blend away from the core value:
 * weight × ln(lens ÷ core), shown left (down) or right (up). The lens
 * values and weights sit beside it.
 */
export function LensContribution({ r }: { r: HMResult }) {
  const core = r.core_value;
  const lenses = r.lenses ?? {};
  const w = r.lens_weights ?? {};
  if (!isNum(core) || !Object.values(lenses).some(isNum)) return <p className="muted small">This result predates the HYBRID MODEL lenses — run the research again.</p>;
  const rows = LENSES.map((l) => {
    const v = lenses[l];
    const wt = w[l];
    const c = isNum(v) && isNum(wt) ? wt * Math.log(v / core) : null;
    return { l, v, wt, c };
  });
  const max = Math.max(0.02, ...rows.map((x) => Math.abs(x.c ?? 0)));
  return (
    <table className="dg dense" style={{ fontSize: 12 }}>
      <thead><tr><th>Lens</th><th className="r">Value</th><th className="r">Weight</th><th style={{ width: "40%" }}>Pull on the blend</th><th className="r">Calibration</th></tr></thead>
      <tbody>
        {rows.map(({ l, v, wt, c }) => {
          const status = r.lenses_dropped?.includes(l) ? "outlier" : !r.lenses_applicable?.includes(l) ? "n/a for type" : !isNum(v) ? "no value" : null;
          return (
            <tr key={l} title={LENS_HINT[l]}>
              <td><span className="row" style={{ gap: 8 }}><i style={{ width: 8, height: 8, borderRadius: 2, background: LENS_COLOR[l], display: "inline-block" }} />{LENS_NAME[l]}{status && <span className="tag">{status}</span>}</span></td>
              <td className="r mono">{money(v, 0)}</td>
              <td className="r mono">{isNum(wt) ? pct(wt, 0) : "—"}</td>
              <td>
                <div className="tbar" style={{ position: "relative", height: 12 }}>
                  {isNum(c) && <span style={{ position: "absolute", top: 2, bottom: 2, borderRadius: 2, background: c >= 0 ? "var(--up)" : "var(--down)", opacity: 0.8, left: c >= 0 ? "50%" : `${50 - (Math.abs(c) / max) * 50}%`, width: `${(Math.abs(c) / max) * 50}%` }} />}
                </div>
              </td>
              <td className="r mono faint">{isNum(r.lens_calibration?.[l]) ? `×${r.lens_calibration![l]!.toFixed(2)}` : "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ------------------------------------------------------------------ bridge */
/** Floating-bar bridge from the blended core to the final HYBRID MODEL value. */
export function Bridge({ r, height = 220 }: { r: HMResult; height?: number }) {
  const [box, width] = useWidth<HTMLDivElement>();
  const core = r.core_value;
  if (!isNum(core) || !isNum(r.value)) return <div ref={box} className="muted small">No bridge for this result.</div>;
  const afterQ = core * r.quality_multiplier;
  const afterH = afterQ * (1 - r.governance_haircut);
  const steps: { label: string; from: number; to: number; kind: "total" | "delta" }[] = [
    { label: "Lens blend", from: 0, to: core, kind: "total" },
    { label: "Quality ×" + r.quality_multiplier.toFixed(2), from: core, to: afterQ, kind: "delta" },
    { label: "Governance −" + pct(r.governance_haircut, 0), from: afterQ, to: afterH, kind: "delta" },
    { label: "Scenarios", from: afterH, to: r.value, kind: "delta" },
    { label: "HYBRID MODEL", from: 0, to: r.value, kind: "total" },
  ];
  if (isNum(r.buy_below)) steps.push({ label: "Buy-below", from: 0, to: r.buy_below, kind: "total" });
  const top = Math.max(...steps.map((s) => Math.max(s.from, s.to)), isNum(r.price) ? r.price : 0) * 1.12;
  const W = Math.max(300, width), H = height, padB = 34, padT = 16;
  const bw = (W / steps.length) * 0.56;
  const y = (v: number) => padT + (1 - v / top) * (H - padT - padB);
  return (
    <div ref={box} style={{ width: "100%" }}>
      {width > 0 && (
        <svg width={W} height={H} style={{ display: "block" }}>
          {niceTicks(0, top, 4).map((t) => (
            <g key={t}><line x1={0} x2={W} y1={y(t)} y2={y(t)} stroke="var(--c-grid)" /><text x={2} y={y(t) - 3} fill="var(--fg-3)" fontSize={9.5} fontFamily="var(--mono)">{money(t, 0)}</text></g>
          ))}
          {isNum(r.price) && (
            <g><line x1={0} x2={W} y1={y(r.price)} y2={y(r.price)} stroke="#E0B97F" strokeDasharray="4 4" /><text x={W - 4} y={y(r.price) - 4} textAnchor="end" fill="#E0B97F" fontSize={10}>price {money(r.price, 0)}</text></g>
          )}
          {steps.map((s, i) => {
            const cx = (W / steps.length) * (i + 0.5);
            const a = Math.max(s.from, s.to), b = Math.min(s.from, s.to);
            const up = s.to >= s.from;
            const fill = s.kind === "total" ? (s.label === "HYBRID MODEL" ? HM_COLOR : s.label === "Buy-below" ? "#86CF86" : "#57A3F8") : up ? "#86CF86" : "#EF8773";
            const d = s.to - s.from;
            return (
              <g key={i}>
                <rect x={cx - bw / 2} y={y(a)} width={bw} height={Math.max(1.5, y(b) - y(a))} rx={2} fill={fill} opacity={s.kind === "total" ? 0.9 : 0.75} />
                {i < steps.length - 1 && steps[i + 1].kind === "delta" && <line x1={cx + bw / 2} x2={cx + W / steps.length - bw / 2} y1={y(s.to)} y2={y(s.to)} stroke="var(--fg-3)" strokeDasharray="2 2" />}
                <text x={cx} y={y(a) - 5} textAnchor="middle" fill="var(--fg-1)" fontSize={10.5} fontFamily="var(--mono)">{s.kind === "total" ? money(s.to, 0) : (d >= 0 ? "+" : "−") + money(Math.abs(d), 0)}</text>
                <text x={cx} y={H - 14} textAnchor="middle" fill="var(--fg-2)" fontSize={10.5}>{s.label}</text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ rate stack */
const PREMIA_COLOR: Record<string, string> = {
  size: "#57A3F8", liquidity: "#4EC9B0", governance: "#EF8773", forensic: "#CD861A",
  leverage: "#C586C0", macro: "#E0B97F", geopolitical: "#AD80D7", earnings_volatility: "#9CDCFE",
};

export function RateStack({ r }: { r: HMResult }) {
  const capm = r.cost_of_equity_capm ?? 0;
  const prem = Object.entries(r.premia ?? {}).filter(([, p]) => isNum(p) && p > 0.00005);
  const total = r.cost_of_equity || capm;
  const scale = Math.max(total, 0.2);
  return (
    <div className="col" style={{ gap: 12 }}>
      <div style={{ display: "flex", height: 20, borderRadius: 4, overflow: "hidden", background: "var(--raise-2)" }}>
        <div style={{ width: `${(capm / scale) * 100}%`, background: "#3a3d41", display: "grid", placeItems: "center", fontSize: 10.5, color: "var(--fg-1)" }}>CAPM {pct(capm, 1)}</div>
        {prem.map(([k, p]) => <div key={k} style={{ width: `${(p / scale) * 100}%`, background: PREMIA_COLOR[k] ?? "#888" }} title={`${titleCase(k)} +${pct(p, 2)}`} />)}
      </div>
      <div className="kv">
        <span className="k">CAPM (floored)</span><span className="v">{pct(capm, 2)}</span>
        {prem.map(([k, p]) => (
          <Frag key={k} k={<span className="row" style={{ gap: 7 }}><i style={{ width: 7, height: 7, borderRadius: 2, background: PREMIA_COLOR[k], display: "inline-block" }} />{titleCase(k)}</span>} v={"+" + pct(p, 2)} />
        ))}
        <span className="k strong">Cost of equity</span><span className="v info">{pct(total, 2)}</span>
      </div>
    </div>
  );
}
function Frag({ k, v }: { k: ReactNode; v: string }) {
  return <><span className="k">{k}</span><span className="v">{v}</span></>;
}

/* ------------------------------------------------------------------ scatter */
export function UpsideScatter({ verdicts, onPick, height = 280 }: { verdicts: Verdict[]; onPick?: (c: string) => void; height?: number }) {
  const data = useMemo(() => verdicts.filter((v) => isNum(v.upside) && isNum(v.confidence)).map((v) => ({
    x: v.confidence, y: Math.max(-0.95, Math.min(3, v.upside as number)) * 100, z: (v.red_flags?.length ?? 0) + 1, name: v.company, label: v.label, upside: v.upside,
  })), [verdicts]);
  if (!data.length) return <div className="muted small" style={{ padding: 20 }}>No company has both a value and a confidence yet.</div>;
  const groups = new Map<string, typeof data>();
  for (const d of data) groups.set(d.label, [...(groups.get(d.label) ?? []), d]);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
        <CartesianGrid strokeDasharray="2 4" />
        <XAxis type="number" dataKey="x" domain={[0, 100]} tickLine={false} axisLine={{ stroke: "var(--line)" }} label={{ value: "Confidence", position: "insideBottomRight", offset: -8, fill: "var(--fg-3)", fontSize: 10.5 }} />
        <YAxis type="number" dataKey="y" unit="%" tickLine={false} axisLine={{ stroke: "var(--line)" }} width={46} />
        <ZAxis type="number" dataKey="z" range={[50, 240]} />
        <ReferenceLine y={0} stroke="var(--c-lines)" />
        <Tooltip cursor={{ strokeDasharray: "3 3", stroke: "#555" }} content={({ active, payload }) => {
          const p = payload?.[0]?.payload as (typeof data)[number] | undefined;
          if (!active || !p) return null;
          return (
            <div className="tip">
              <div className="tt">{shortName(p.name)}</div>
              <div className="tr"><span>Label</span><span style={{ color: LABEL_HEX[p.label] }}>{p.label}</span></div>
              <div className="tr"><span>Upside</span><span className="mono">{pct(p.upside, 1, true)}</span></div>
              <div className="tr"><span>Confidence</span><span className="mono">{p.x.toFixed(0)}</span></div>
              <div className="tr"><span>Red flags</span><span className="mono">{p.z - 1}</span></div>
            </div>
          );
        }} />
        {[...groups.entries()].map(([label, pts]) => (
          <Scatter key={label} name={label} data={pts} fill={LABEL_HEX[label] ?? "var(--fg-3)"} fillOpacity={0.85} cursor={onPick ? "pointer" : undefined} onClick={(d: { name?: string }) => d?.name && onPick?.(d.name)} />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------------------------------------------ treemap */
function upColor(u: number | null | undefined) {
  if (!isNum(u)) return "#2c2d2e";
  const t = Math.max(-1, Math.min(1, u / 0.6));
  const mix = (a: number[], b: number[]) => a.map((x, i) => Math.round(x + (b[i] - x) * Math.abs(t)));
  const base = [44, 45, 46];
  const c = t >= 0 ? mix(base, [52, 120, 72]) : mix(base, [150, 62, 50]);
  return `rgb(${c.join(",")})`;
}

interface TmNode { name: string; size: number; upside: number | null; label: string; sector: string; flags: number; [k: string]: unknown }

export function CoverageMap({ verdicts, onPick, height = 360 }: { verdicts: Verdict[]; onPick: (c: string) => void; height?: number }) {
  const data = useMemo(() => {
    const m = new Map<string, TmNode[]>();
    for (const v of verdicts) {
      const cap = (v as unknown as { base?: { market_cap_cr?: number } }).base?.market_cap_cr;
      const node: TmNode = { name: v.company, size: Math.max(1, isNum(cap) ? Math.sqrt(cap) : 50), upside: v.upside, label: v.label, sector: v.sector || "Other", flags: v.red_flags?.length ?? 0 };
      m.set(node.sector, [...(m.get(node.sector) ?? []), node]);
    }
    return [...m.entries()].map(([name, children]) => ({ name, children }));
  }, [verdicts]);
  if (!verdicts.length) return null;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <Treemap data={data} dataKey="size" aspectRatio={1.6} isAnimationActive={false}
        content={<TmCell onPick={onPick} /> as unknown as React.ReactElement}>
        <Tooltip content={({ active, payload }) => {
          const p = payload?.[0]?.payload as TmNode | undefined;
          if (!active || !p || p.upside === undefined) return null;
          return (
            <div className="tip">
              <div className="tt">{shortName(p.name)}</div>
              <div className="tr"><span>Sector</span><span>{p.sector}</span></div>
              <div className="tr"><span>Upside</span><span className="mono">{pct(p.upside, 1, true)}</span></div>
              <div className="tr"><span>Label</span><span style={{ color: LABEL_HEX[p.label] }}>{p.label}</span></div>
              {p.flags > 0 && <div className="tr"><span>Red flags</span><span className="mono down">{p.flags}</span></div>}
            </div>
          );
        }} />
      </Treemap>
    </ResponsiveContainer>
  );
}

function TmCell(props: { x?: number; y?: number; width?: number; height?: number; depth?: number; name?: string; upside?: number | null; flags?: number; onPick: (c: string) => void }) {
  const { x = 0, y = 0, width = 0, height = 0, depth = 0, name = "", upside, flags, onPick } = props;
  if (depth === 1) {
    return (
      <g>
        <rect x={x} y={y} width={width} height={height} fill="none" stroke="var(--bg)" strokeWidth={3} />
        {width > 80 && <text x={x + 6} y={y + 14} fill="#ececedcc" fontSize={10} fontWeight={700} letterSpacing=".04em">{name.toUpperCase().slice(0, Math.floor(width / 7))}</text>}
      </g>
    );
  }
  if (depth !== 2) return null;
  const show = width > 56 && height > 34;
  return (
    <g className="tm-cell" onClick={() => onPick(name)}>
      <rect x={x + 1} y={y + 1} width={Math.max(0, width - 2)} height={Math.max(0, height - 2)} rx={3} fill={upColor(upside)} stroke="var(--bg)" strokeWidth={1} />
      {show && <text x={x + 7} y={y + 18} fill="#f2f2f2" fontSize={11.5} fontWeight={600}>{shortName(name).slice(0, Math.max(4, Math.floor(width / 7.2)))}</text>}
      {show && <text x={x + 7} y={y + 34} fill="#ffffffcc" fontSize={11} fontFamily="var(--mono)">{pct(upside, 0, true)}</text>}
      {show && (flags ?? 0) > 0 && <circle cx={x + width - 10} cy={y + 12} r={4} fill="#EF8773" />}
    </g>
  );
}
