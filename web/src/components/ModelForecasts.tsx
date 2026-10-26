import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useValuation } from "../lib/hooks";
import { Verdict } from "../lib/api";
import { forecast, HORIZONS, learnSkills, ModelForecast } from "../lib/forecast";
import { isNum, money, pct } from "../lib/format";
import { HM, HM_COLOR, SERIES } from "../lib/labels";
import { metricName } from "../lib/metrics";
import { ExportButton } from "./ExportButton";
import { Empty, Icon, Panel, QueryView, Tip } from "./ui";

type Span = "days" | "months" | "years";
const SPANS: { id: Span; label: string; steps: { t: number; x: string }[] }[] = [
  { id: "days", label: "Days", steps: Array.from({ length: 31 }, (_, d) => ({ t: d / 365, x: d ? `${d}d` : "Now" })) },
  { id: "months", label: "Months", steps: Array.from({ length: 13 }, (_, m) => ({ t: m / 12, x: m ? `${m}m` : "Now" })) },
  { id: "years", label: "Years", steps: Array.from({ length: 21 }, (_, q) => ({ t: q / 4, x: !q ? "Now" : q % 4 ? `${q >= 4 ? `${Math.floor(q / 4)}y ` : ""}${(q % 4) * 3}m` : `${q / 4}y` })) },
];

const colourOf = (m: string, i: number) => (m === HM ? HM_COLOR : SERIES[i % SERIES.length]);
const convColour = (c: number) => (c >= 60 ? "var(--up)" : c >= 40 ? "var(--c-yellow, #E0B97F)" : "var(--down)");

/** Every model's predicted price path for this company, and how strongly each one believes it. */
export function ModelForecasts({ v }: { v: Verdict }) {
  const q = useValuation();
  return (
    <QueryView q={q} rows={6}>
      {(d) => {
        const mine = d.rows.filter((r) => r.company === v.company).sort((a, b) => a.fy.localeCompare(b.fy));
        if (!d.available || !mine.length || !isNum(v.price) || v.price <= 0) {
          return <Panel title="Model forecasts"><Empty icon="graph-line" title="No model values for this company yet">Run the valuation report, then each model's predicted path appears here.</Empty></Panel>;
        }
        return <Forecasts v={v} price={v.price} rows={d.rows} models={d.models} mine={mine} />;
      }}
    </QueryView>
  );
}

function Forecasts({ v, price, rows, models, mine }: { v: Verdict; price: number; rows: Parameters<typeof learnSkills>[0]; models: string[]; mine: Parameters<typeof learnSkills>[0] }) {
  const [span, setSpan] = useState<Span>("months");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [focus, setFocus] = useState<string | null>(null);
  const skills = useMemo(() => learnSkills(rows, models), [rows, models]);
  const list = useMemo(() => {
    const latest = mine[mine.length - 1];
    const values: Record<string, number> = {};
    for (const m of models) { const x = latest.values?.[m]; if (isNum(x) && x > 0) values[m] = x; }
    // the research run's own HYBRID MODEL value is the one the page shows
    if (isNum(v.expected_value) && v.expected_value > 0) values[HM] = v.expected_value;
    // values compound at the long-run rate: the near-term rate would carry every model upward
    return forecast(price, values, skills, mine, isNum(v.growth_terminal) ? v.growth_terminal : v.growth);
  }, [mine, models, skills, price, v.expected_value, v.growth, v.growth_terminal]);
  const colour = useMemo(() => Object.fromEntries(models.map((m, i) => [m, colourOf(m, i)])), [models]);
  const steps = SPANS.find((s) => s.id === span)!.steps;
  const shown = list.filter((f) => !hidden.has(f.model));
  const data = useMemo(() => steps.map(({ t, x }) => {
    const row: Record<string, number | string | [number, number]> = { x };
    for (const f of shown) { const p = f.at(t); row[f.model] = p.mid; }
    return row;
  }), [steps, shown]);
  const top = list[0];
  const consensus = useMemo(() => {
    const w = list.reduce((s, f) => s + f.conviction, 0) || 1;
    return (t: number) => list.reduce((s, f) => s + f.at(t).mid * f.conviction, 0) / w;
  }, [list]);
  const toggle = (m: string) => setHidden((h) => { const n = new Set(h); if (n.has(m)) n.delete(m); else n.add(m); return n; });

  const exportTable = () => ({
    head: ["Model", "Value now", ...HORIZONS.map((h) => h.label), "Conviction", "Gap closed per year", "Hit ±20%"],
    rows: list.map((f) => [metricName(f.model), Math.round(f.value), ...HORIZONS.map((h) => Math.round(f.at(h.years).mid)), f.conviction, `${Math.round(f.beta * 100)}%`, `${Math.round(f.hit * 100)}%`]),
    subtitle: `${v.company} · price ${money(price)} · projections from the valuation report's history, not promises`,
  });

  return (
    <>
      <div className="band fc-band">
        <div><div className="k">Weighted view, 1 year</div><div className="v">{money(consensus(1), 0)}</div><div className={`s ${consensus(1) >= price ? "up" : "down"}`}>{pct(consensus(1) / price - 1, 1, true)} from {money(price, 0)}</div></div>
        <div><div className="k">Most convinced</div><div className="v row" style={{ gap: 8 }}><i className="fc-sw" style={{ background: colour[top.model] }} />{metricName(top.model)}</div><div className="s">{top.conviction}/100 · {money(top.at(1).mid, 0)} in a year</div></div>
        <div><div className="k">Rising in a year</div><div className="v">{list.filter((f) => f.at(1).mid > price).length}/{list.length}</div><div className="s">models above today's price</div></div>
        <div><div className="k">Least predictable</div><div className="v">{(() => { const w = [...list].sort((a, b) => b.sigma - a.sigma)[0]; return metricName(w.model); })()}</div><div className="s">widest range of outcomes</div></div>
      </div>

      <Panel title="Predicted price, by model" meta="from today's price toward each model's value" exportTitle={`${v.company} — predicted price by model`}
        tools={<>
          <div className="seg">{SPANS.map((s) => <button key={s.id} className={span === s.id ? "on" : ""} onClick={() => setSpan(s.id)}>{s.label}</button>)}</div>
        </>}>
        <div>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 4 }}>
              <CartesianGrid strokeDasharray="2 4" />
              <XAxis dataKey="x" tickLine={false} axisLine={{ stroke: "var(--line)" }} minTickGap={18} />
              <YAxis tickLine={false} axisLine={false} width={74} tickFormatter={(x) => money(x, 0)} domain={["auto", "auto"]} />
              <Tooltip content={<Tip fmt={(x) => money(x as number, 0)} />} itemSorter={(p) => -Number(p.value ?? 0)} />
              <ReferenceLine y={price} stroke="var(--price)" strokeDasharray="4 4" label={{ value: `price ${money(price, 0)}`, position: "insideTopLeft", fill: "var(--fg-3)", fontSize: 11 }} />
              {shown.map((f) => (
                <Line key={f.model} type="monotone" dataKey={f.model} name={metricName(f.model)} stroke={colour[f.model]} dot={false} isAnimationActive={false}
                  strokeWidth={focus === f.model || (f.model === HM && !focus) ? 3 : 1.6} strokeOpacity={focus && focus !== f.model ? 0.25 : 1} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="fc-legend">
          {list.map((f) => (
            <button key={f.model} className={hidden.has(f.model) ? "off" : ""} onClick={() => toggle(f.model)} onMouseEnter={() => setFocus(f.model)} onMouseLeave={() => setFocus(null)} title={hidden.has(f.model) ? "Show" : "Hide"}>
              <i style={{ background: colour[f.model] }} />{metricName(f.model)}
            </button>
          ))}
          {hidden.size > 0 && <button className="reset" onClick={() => setHidden(new Set())}>Show all</button>}
        </div>
      </Panel>

      <Panel title="Forecast table" meta="hover a price for its range, a conviction for its parts" flush noExport
        tools={<ExportButton title={`${v.company} model forecasts`} table={exportTable} />}>
        <div className="dg-wrap">
          <table className="dg dense fc-table">
            <thead><tr>
              <th>Model</th><th className="r">Value now</th>
              {HORIZONS.map((h) => <th key={h.id} className="r">{h.label}</th>)}
              <th style={{ width: 150 }}>Conviction</th>
            </tr></thead>
            <tbody>
              {list.map((f) => (
                <tr key={f.model} className={focus === f.model ? "sel" : ""} onMouseEnter={() => setFocus(f.model)} onMouseLeave={() => setFocus(null)}>
                  <td><span className="row" style={{ gap: 6 }}><i className="fc-sw" style={{ background: colour[f.model] }} /><span className={f.model === HM ? "hm strong" : ""}>{metricName(f.model)}</span></span></td>
                  <td className="r mono">{money(f.value, 0)}</td>
                  {HORIZONS.map((h) => { const p = f.at(h.years).mid; return <td key={h.id} className={`r mono ${p >= price ? "up" : "down"}`} title={`${money(f.at(h.years).lo, 0)} – ${money(f.at(h.years).hi, 0)} (one spread either side)`}>{money(p, 0)}</td>; })}
                  <td><Conviction f={f} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="fc-note xs faint"><Icon name="info" className="xs" />Projections from how prices have moved against each model's values in the report — not advice and not promises. Conviction blends how well each model's gaps foretold next year's move ({"35%"}), its hit rate within ±20% ({"25%"}), how steady its view of this company has been ({"20%"}) and how close it sits to the other models ({"20%"}).</div>
      </Panel>
    </>
  );
}

function Conviction({ f }: { f: ModelForecast }) {
  const tip = `Signal ${Math.round(f.parts.signal * 100)} · accuracy ${Math.round(f.parts.accuracy * 100)} · steadiness ${Math.round(f.parts.stability * 100)} · agreement ${Math.round(f.parts.agreement * 100)}\nThe market has closed ${Math.round(f.beta * 100)}% of this model's gap a year (${f.n} company-years).`;
  return (
    <span className="fc-conv" title={tip}>
      <span className="bar"><i style={{ width: `${f.conviction}%`, background: convColour(f.conviction) }} /></span>
      <b className="mono">{f.conviction}</b>
    </span>
  );
}
