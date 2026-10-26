// Accuracy metrics computed in the page, for any subset of companies (a
// watchlist). The same definitions as the report's analysis stage
// (src/csv_analyzer.py): error = (value - price) / price against the 1-May price.
import { CsvRow, ValuationRow } from "./api";
import { isNum } from "./format";

const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b), m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const ranks = (xs: number[]) => {
  const order = xs.map((v, i) => [v, i] as const).sort((a, b) => a[0] - b[0]);
  const r = new Array(xs.length);
  for (let i = 0; i < order.length;) {
    let j = i;
    while (j + 1 < order.length && order[j + 1][0] === order[i][0]) j++;
    for (let k = i; k <= j; k++) r[order[k][1]] = (i + j) / 2 + 1;
    i = j + 1;
  }
  return r as number[];
};
function spearman(a: number[], b: number[]) {
  if (a.length < 3) return null;
  const ra = ranks(a), rb = ranks(b), n = a.length;
  const ma = ra.reduce((x, y) => x + y, 0) / n, mb = rb.reduce((x, y) => x + y, 0) / n;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) { num += (ra[i] - ma) * (rb[i] - mb); da += (ra[i] - ma) ** 2; db += (rb[i] - mb) ** 2; }
  return da && db ? num / Math.sqrt(da * db) : null;
}

function stats(pairs: { v: number; p: number }[]) {
  const err = pairs.map(({ v, p }) => (v - p) / p);
  const ape = err.map(Math.abs);
  return {
    "MedAPE %": median(ape) != null ? median(ape)! * 100 : null,
    "Hit +/-20%": ape.length ? (100 * ape.filter((x) => x <= 0.2).length) / ape.length : null,
    "Bias %": err.length ? (100 * err.reduce((x, y) => x + y, 0)) / err.length : null,  // mean signed error, as the report
    Spearman: spearman(pairs.map((x) => x.v), pairs.map((x) => x.p)),
    N: pairs.length,
  };
}

/** "P/E Relative Valuation" -> "P/E Relative": the metric files' model names */
export const metricName = (m: string) => m.replace(/ Valuation$/, "");

/** {overall, by_year, by_sector, win_rate} for these rows, shaped like the report's metric files. */
export function computeMetrics(rows: ValuationRow[], models: string[]) {
  const pairs = (m: string, keep: (r: ValuationRow) => boolean = () => true) =>
    rows.filter(keep).map((r) => ({ v: r.values?.[m], p: r.price })).filter((x): x is { v: number; p: number } => isNum(x.v) && isNum(x.p) && x.p > 0 && x.v > 0);
  const overall: CsvRow[] = models.map((m) => ({ Model: metricName(m), ...stats(pairs(m)) })).filter((r) => (r.N as number) > 0);
  const years = [...new Set(rows.map((r) => r.fy))].sort();
  const by_year: CsvRow[] = years.flatMap((y) => models.map((m) => ({ "Financial Year": y, Model: metricName(m), ...stats(pairs(m, (r) => r.fy === y)) })).filter((r) => (r.N as number) > 0));
  const sectors = [...new Set(rows.map((r) => r.sector))].sort();
  const by_sector: CsvRow[] = sectors.flatMap((s) => models.map((m) => ({ "Sector Name": s, Model: metricName(m), ...stats(pairs(m, (r) => r.sector === s)) })).filter((r) => (r.N as number) > 0));
  // win: the model closest to the price on a company-year where at least two models answered
  const wins = new Map<string, number>(), chances = new Map<string, number>();
  for (const r of rows) {
    if (!isNum(r.price) || r.price <= 0) continue;
    const got = models.map((m) => [m, r.values?.[m]] as const).filter((x): x is readonly [string, number] => isNum(x[1]) && x[1] > 0);
    if (got.length < 2) continue;
    let best = got[0];
    for (const g of got) if (Math.abs(g[1] - r.price) < Math.abs(best[1] - r.price)) best = g;
    for (const [m] of got) chances.set(m, (chances.get(m) ?? 0) + 1);
    wins.set(best[0], (wins.get(best[0]) ?? 0) + 1);
  }
  const win_rate: CsvRow[] = models.filter((m) => chances.get(m)).map((m) => ({ Model: metricName(m), "Win rate %": (100 * (wins.get(m) ?? 0)) / chances.get(m)! }))
    .sort((a, b) => (b["Win rate %"] as number) - (a["Win rate %"] as number));
  return { overall, by_year, by_sector, win_rate };
}
