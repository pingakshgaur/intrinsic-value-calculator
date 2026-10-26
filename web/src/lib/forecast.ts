// Per-model price paths for one company, learned from the valuation report.
//
// For every model, across every company and pair of consecutive financial
// years, the report shows how much of the gap between the model's value and
// the price closed by the next year's price:  next move = β · gap + ε, in logs.
// β is how fast the market has followed that model, ε's spread is how far it
// strays. A company's path then starts at today's price and closes (1-β)^t of
// the gap each year toward the model's value, which itself grows at the
// company's long-run growth rate. These are projections from history, not promises.
import { ValuationRow } from "./api";
import { isNum } from "./format";

export interface Horizon { id: string; label: string; years: number }
export const HORIZONS: Horizon[] = [
  { id: "1w", label: "1 week", years: 7 / 365 },
  { id: "1m", label: "1 month", years: 1 / 12 },
  { id: "3m", label: "1 quarter", years: 0.25 },
  { id: "6m", label: "6 months", years: 0.5 },
  { id: "1y", label: "1 year", years: 1 },
  { id: "3y", label: "3 years", years: 3 },
  { id: "5y", label: "5 years", years: 5 },
];

/** What the report taught about one model, across every company. */
export interface ModelSkill {
  model: string;
  beta: number;    // share of the gap that closes in a year, 0..1
  sigma: number;   // yearly spread of what the line does not explain (log)
  corr: number;    // how well the gap foretold the move, -1..1
  hit: number;     // share of company-years within ±20% of the price, 0..1
  n: number;       // pairs the line was fitted on
}

export interface ModelForecast extends ModelSkill {
  value: number;                 // the model's value for this company now
  gap: number;                   // log(value / price)
  conviction: number;            // 0..100
  parts: { signal: number; accuracy: number; stability: number; agreement: number };
  at: (years: number) => { mid: number; lo: number; hi: number };
}

const clamp = (x: number, a: number, b: number) => Math.max(a, Math.min(b, x));
const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const sd = (xs: number[]) => { const m = mean(xs); return Math.sqrt(mean(xs.map((x) => (x - m) ** 2))); };
const median = (xs: number[]) => { const s = [...xs].sort((a, b) => a - b); const m = s.length >> 1; return s.length ? (s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2) : NaN; };
const ok = (x: unknown): x is number => isNum(x) && x > 0;

/** Fit β, σ and the hit rate for every model on the whole report. */
export function learnSkills(rows: ValuationRow[], models: string[]): Record<string, ModelSkill> {
  const byCo = new Map<string, ValuationRow[]>();
  for (const r of rows) (byCo.get(r.company) ?? byCo.set(r.company, []).get(r.company)!).push(r);
  for (const list of byCo.values()) list.sort((a, b) => a.fy.localeCompare(b.fy));
  const out: Record<string, ModelSkill> = {};
  for (const m of models) {
    const gaps: number[] = [], moves: number[] = [];
    let hits = 0, seen = 0;
    for (const list of byCo.values()) {
      for (let i = 0; i < list.length; i++) {
        const a = list[i], v = a.values?.[m];
        if (!ok(v) || !ok(a.price)) continue;
        seen++; if (Math.abs(v / a.price - 1) <= 0.2) hits++;
        const b = list[i + 1];
        if (!b || !ok(b.price)) continue;
        gaps.push(Math.log(v / a.price)); moves.push(Math.log(b.price / a.price));
      }
    }
    // a line through the origin keeps the fit honest when the report is short
    const sxx = gaps.reduce((s, g) => s + g * g, 0), sxy = gaps.reduce((s, g, i) => s + g * moves[i], 0);
    const raw = sxx > 0 ? sxy / sxx : 0;
    const beta = clamp(raw, 0, 1);
    const resid = moves.map((y, i) => y - beta * gaps[i]);
    const mg = mean(gaps), mm = mean(moves);
    const cov = mean(gaps.map((g, i) => (g - mg) * (moves[i] - mm)));
    const corr = gaps.length > 2 && sd(gaps) > 0 && sd(moves) > 0 ? cov / (sd(gaps) * sd(moves)) : 0;
    out[m] = { model: m, beta, sigma: gaps.length > 2 ? clamp(sd(resid), 0.05, 1.2) : 0.35, corr, hit: seen ? hits / seen : 0, n: gaps.length };
  }
  return out;
}

/**
 * Every model's path for one company. `values` are the models' values now,
 * `history` the company's own report rows (for how steady each model has been),
 * `growth` the yearly long-run growth of value.
 */
export function forecast(price: number, values: Record<string, number>, skills: Record<string, ModelSkill>, history: ValuationRow[], growth: number): ModelForecast[] {
  const g = clamp(isNum(growth) ? growth : 0.08, -0.1, 0.25);
  const logs = Object.values(values).filter(ok).map(Math.log);
  const consensus = median(logs);
  return Object.entries(values).filter(([m, v]) => ok(v) && skills[m]).map(([m, v]) => {
    const s = skills[m];
    const gap = Math.log(v / price);
    // steadiness: how much this model's view of the company swung from year to year
    const own = history.map((r) => (ok(r.values?.[m]) && ok(r.price) ? Math.log(r.values[m] / r.price) : null)).filter(isNum) as number[];
    const stability = own.length > 1 ? Math.exp(-1.5 * sd(own)) : 0.5;
    const agreement = Math.exp(-2 * Math.abs(Math.log(v) - consensus));
    const signal = clamp(s.corr, 0, 1) * Math.min(1, s.n / 20);
    const accuracy = s.hit;
    const conviction = Math.round(100 * clamp(0.35 * signal + 0.25 * accuracy + 0.2 * stability + 0.2 * agreement, 0, 1));
    const at = (t: number) => {
      const left = Math.pow(1 - s.beta, t);
      const mid = Math.log(v) + Math.log(1 + g) * t - gap * left;
      const w = s.sigma * Math.sqrt(t);
      return { mid: Math.exp(mid), lo: Math.exp(mid - w), hi: Math.exp(mid + w) };
    };
    return { ...s, value: v, gap, conviction, parts: { signal, accuracy, stability, agreement }, at };
  }).sort((a, b) => b.conviction - a.conviction);
}
