import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ForecastHorizon, isOpen, useForecast } from "../lib/live";
import { ago, isNum, money, pct } from "../lib/format";
import { HM_COLOR } from "../lib/labels";
import { ErrorNote, Icon, Loading, Panel } from "./ui";

const SHORT: Record<string, string> = { "15m": "15 min", "1h": "1 hr", "1d": "1 day", "1w": "1 wk", "1m": "1 mo", "3m": "3 mo", "6m": "6 mo", "1y": "1 yr", "3y": "3 yr", "5y": "5 yr" };
const DRIVER: Record<ForecastHorizon["lead"], string> = {
  drift: "market drift", reversal: "recent moves", momentum: "3-month trend", value: "pull to model value",
};

/**
 * Where the price may be in 15 minutes, an hour, a day ... five years: a
 * median with a P10-P90 band and the chance it ends higher, recomputed with
 * every tracker poll while the market is open.
 */
export function LiveForecast({ ticker, compact }: { ticker: string; compact?: boolean }) {
  const q = useForecast(ticker);
  const d = q.data;
  if (q.isError) return <Panel title="Live forecast"><ErrorNote error={q.error} /></Panel>;
  if (!d) return <Panel title="Live forecast"><Loading rows={4} /></Panel>;
  const open = isOpen(d.market);
  const hs = compact ? d.horizons.filter((h) => ["15m", "1h", "1d", "1w", "1m", "1y"].includes(h.key)) : d.horizons;
  const chart = [{ label: "Now", price: d.price, band: [d.price, d.price] as [number, number] }, ...d.horizons.map((h) => ({ label: SHORT[h.key] ?? h.key, price: h.price, band: [h.low, h.high] as [number, number] }))];
  const a1 = d.accuracy["1d"], a15 = d.accuracy["15m"];
  return (
    <Panel title="Live forecast" className="lf"
      meta={<span className="row" style={{ gap: 6 }}><span className={`live-dot ${open && d.live ? "on" : ""}`}>{open ? (d.live ? "live" : "market open · waiting for a quote") : "market closed"}</span><span>from {money(d.price)} · updated {ago(d.computed)}</span></span>}
      exportTitle={`${d.name} — live forecast`}>
      <div className="lf-strip">
        {hs.map((h) => (
          <div key={h.key} className="lf-h" title={`${h.label}: median ${money(h.price)}; 8 in 10 outcomes between ${money(h.low)} and ${money(h.high)}. Main driver: ${DRIVER[h.lead]}.`}>
            <div className="k">{h.label}</div>
            <div className="v mono">{money(h.price, h.price < 100 ? 2 : 0)}</div>
            <div className={`c mono ${h.change >= 0 ? "up" : "down"}`}>{pct(h.change, Math.abs(h.change) < 0.01 ? 2 : 1, true)}</div>
            <div className="b mono">{money(h.low, 0)}–{money(h.high, 0)}</div>
            <div className="p"><div className="lf-pu"><i style={{ width: `${h.p_up * 100}%` }} /></div><span>{Math.round(h.p_up * 100)}% higher</span></div>
            <div className="d">{DRIVER[h.lead]}</div>
          </div>
        ))}
      </div>
      {!compact && (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={chart} margin={{ top: 10, right: 16, bottom: 0, left: 4 }}>
            <CartesianGrid strokeDasharray="2 4" />
            <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "var(--line)" }} interval={0} tick={{ fontSize: 10.5 }} />
            <YAxis tickLine={false} axisLine={false} width={70} domain={["auto", "auto"]} tickFormatter={(x) => money(x, 0)} />
            <Tooltip content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0].payload as (typeof chart)[number];
              return <div className="tip"><div className="tt">{label}</div><div className="tr"><span>Median</span><span className="mono strong">{money(p.price)}</span></div><div className="tr"><span>P10–P90</span><span className="mono strong">{money(p.band[0], 0)} – {money(p.band[1], 0)}</span></div></div>;
            }} />
            <Area type="monotone" dataKey="band" name="P10–P90" stroke="none" fill="#57A3F8" fillOpacity={0.16} />
            <Line type="monotone" dataKey="price" name="Median" stroke="#57A3F8" strokeWidth={2.2} dot={{ r: 2.5 }} />
            <ReferenceLine y={d.price} stroke="var(--price)" strokeDasharray="4 3" label={{ value: "now", position: "insideTopLeft", fill: "var(--fg-3)", fontSize: 10 }} />
            {isNum(d.value?.value) && <ReferenceLine y={d.value!.value!} stroke={HM_COLOR} strokeDasharray="4 3" label={{ value: "HYBRID MODEL", position: "insideBottomRight", fill: HM_COLOR, fontSize: 10 }} />}
          </ComposedChart>
        </ResponsiveContainer>
      )}
      <div className="lf-foot xs">
        {(a1 || a15) && <span className="lf-acc"><Icon name="history" className="xs" />Tested on its own past:{a1 && <> the 1-day direction was right <b>{Math.round(a1.direction * 100)}%</b> of the last {a1.n} sessions and the 1-day band held the outcome <b>{Math.round(a1.band * 100)}%</b> of the time</>}{a1 && a15 && ";"}{a15 && <> the 15-minute direction <b>{Math.round(a15.direction * 100)}%</b> of {a15.n} intervals</>}.</span>}
        {d.notes.map((n) => <span key={n} className="faint"><Icon name="info" className="xs" />{n}</span>)}
        <details className="lf-how">
          <summary>How it is worked out</summary>
          <p>Each horizon is a median price and a band that holds 8 in 10 outcomes, from this stock's own volatility (recent for short horizons, long-run for long ones).
            The median moves with the market's long-run drift, a small reversal or follow-through of the latest 15-minute and daily moves (fitted to its own history),
            a shrunk 3-month trend, and — from months out — a pull towards the HYBRID MODEL value, closing half the gap about every 1.7 years, weighted by the model's confidence.
            Inputs: {d.inputs.daily_closes.toLocaleString("en-IN")} daily closes ({d.inputs.daily_source ?? "none"}), {d.inputs.minute_bars.toLocaleString("en-IN")} stored minute bars; daily volatility {pct(d.inputs.sigma_day, 2)}.</p>
          <p>A statistical projection, not advice: it cannot see news, results or the order book.</p>
        </details>
      </div>
    </Panel>
  );
}
