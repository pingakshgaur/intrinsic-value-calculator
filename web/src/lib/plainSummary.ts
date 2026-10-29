// A short, plain-English reading of one company's research and forecasts,
// for someone who does not want the jargon: is it cheap, how sure are we,
// what could go right or wrong, and what the models expect a year out.
import { Verdict } from "./api";
import { isNum, money, pct, shortName } from "./format";
import { LEAD_SHORT } from "./labels";

export interface PlainSummary {
  /** the bottom line, a few words */
  headline: string;
  tone: "up" | "down" | "info" | "warn";
  /** three to six sentences */
  paragraph: string;
  good: string[];
  watch: string[];
}

const sure = (c: number) => (c >= 70 ? "fairly confident" : c >= 50 ? "moderately confident" : "not very confident");
const near = (x: number, d = 0) => `${pct(Math.abs(x), d)}`;

export function plainSummary(v: Verdict, forecast?: { rising: number; total: number; oneYear: number } | null): PlainSummary {
  const name = shortName(v.company);
  const price = v.price, value = v.expected_value, up = v.upside;
  const flags = v.red_flags ?? [];
  const s: string[] = [];
  let headline = "Not enough evidence for a clear view";
  let tone: PlainSummary["tone"] = "info";

  if (isNum(price) && isNum(value) && isNum(up)) {
    const view = up > 0.15 ? "looks cheap" : up < -0.1 ? "looks expensive" : "looks about fairly priced";
    s.push(`${name} trades at ${money(price, 0)}. Our main model (the HYBRID MODEL) puts its fair value at about ${money(value, 0)}, so the share ${view}` +
      (Math.abs(up) >= 0.03 ? ` — roughly ${near(up)} ${up >= 0 ? "below" : "above"} what we think it is worth.` : "."));
    if (v.label === "Avoid - red flags") { headline = "Warning signs outweigh the price"; tone = "down"; }
    else if (up > 0.15) { headline = `Looks undervalued — about ${near(up)} upside`; tone = "up"; }
    else if (up < -0.1) { headline = `Looks overvalued — about ${near(up)} above fair value`; tone = "warn"; }
    else { headline = "Looks fairly priced — limited room either way"; tone = "info"; }
  }

  if (isNum(v.confidence)) {
    const range = isNum(v.low) && isNum(v.high) ? ` and the fair value could reasonably sit anywhere from ${money(v.low, 0)} to ${money(v.high, 0)}` : "";
    s.push(`We are ${sure(v.confidence)} in this (${v.confidence.toFixed(0)} out of 100)${range}.`);
  }

  if (isNum(v.buy_below) && isNum(price)) {
    s.push(price <= v.buy_below
      ? `It is already below ${money(v.buy_below, 0)}, the price at which a cautious buyer would have a safety cushion.`
      : `A cautious buyer would wait for a price under ${money(v.buy_below, 0)}, about ${near(v.buy_below / price - 1)} lower than today.`);
  }

  if (forecast && forecast.total > 0 && isNum(price)) {
    const move = forecast.oneYear / price - 1;
    s.push(`Looking a year ahead, ${forecast.rising} of ${forecast.total} valuation models expect the price to be higher; together they point to about ${money(forecast.oneYear, 0)} (${pct(move, 0, true)}).`);
  }

  const p = v.probabilities;
  if (p && isNum(v.bull_value) && isNum(v.bear_value)) {
    s.push(`If things go well it could be worth ${money(v.bull_value, 0)} (${pct(p.bull, 0)} chance); if they go badly, ${money(v.bear_value, 0)} (${pct(p.bear, 0)} chance).`);
  }

  // the research leads: what helps and what worries
  const leads = [...(v.leads ?? [])].filter((l) => isNum(l.score)).sort((a, b) => b.score - a.score);
  const good: string[] = [], watch: string[] = [];
  for (const l of leads) {
    const label = LEAD_SHORT[l.lead] ?? l.name;
    if (l.score >= 0.15) good.push(`${label} findings are positive`);
    else if (l.score <= -0.15) watch.push(`${label} findings are negative`);
  }
  if (flags.length) watch.unshift(...flags.slice(0, 3));
  else good.push("No validated warning signs");
  for (const w of v.summary?.watch_next ?? []) if (watch.length < 5) watch.push(w);
  if (flags.length) s.push(`${flags.length} warning sign${flags.length === 1 ? " was" : "s were"} found — see the list below.`);

  return { headline, tone, paragraph: s.join(" "), good: good.slice(0, 4), watch: watch.slice(0, 5) };
}
