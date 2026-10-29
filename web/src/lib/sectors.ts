// Sector views of the valuation report: which model is most accurate in each
// sector, what each model says each sector is worth now, and how the sectors
// split into below / near / above value with a one-year projection.
//
// Accuracy is the report's own (median absolute % error against the 1-May
// price). The projection uses each model's history, as on the company page:
// the market has closed a share β of a model's gap to the price each year,
// so a gap g (in logs) projects a move of exp(β·g) - 1 over the next year.
import { CsvRow, ValuationRow } from "./api";
import { isNum } from "./format";
import { learnSkills, ModelSkill } from "./forecast";
import { metricName } from "./metrics";

const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const ok = (x: unknown): x is number => isNum(x) && x > 0;

export interface SectorBest {
  sector: string;
  ranked: { model: string; err: number; hit: number | null; n: number }[];
  best: string;
  bestErr: number;
  /** how much better the best model is than the median model, in error points */
  margin: number;
  n: number;
}

/** The most accurate model in each sector, from by-sector metric rows. */
export function bestBySector(rows: CsvRow[]): SectorBest[] {
  const by = new Map<string, SectorBest["ranked"]>();
  for (const r of rows) {
    const e = r["MedAPE %"];
    if (!isNum(e)) continue;
    const s = String(r["Sector Name"] ?? "Unclassified");
    (by.get(s) ?? by.set(s, []).get(s)!).push({ model: String(r.Model), err: e, hit: isNum(r["Hit +/-20%"]) ? r["Hit +/-20%"] : null, n: isNum(r.N) ? r.N : 0 });
  }
  return [...by.entries()].map(([sector, ranked]) => {
    ranked.sort((a, b) => a.err - b.err);
    const mid = median(ranked.map((x) => x.err)) ?? ranked[0].err;
    return { sector, ranked, best: ranked[0].model, bestErr: ranked[0].err, margin: mid - ranked[0].err, n: Math.max(...ranked.map((x) => x.n)) };
  }).sort((a, b) => a.sector.localeCompare(b.sector));
}

/** How often each model is the best one across sectors. */
export function winsBySector(best: SectorBest[]) {
  const n = new Map<string, number>();
  for (const b of best) n.set(b.best, (n.get(b.best) ?? 0) + 1);
  return [...n.entries()].map(([model, sectors]) => ({ model, sectors })).sort((a, b) => b.sectors - a.sectors);
}

/** Each company's latest report row. */
export function latestRows(rows: ValuationRow[]) {
  const last = new Map<string, ValuationRow>();
  for (const r of rows) {
    const cur = last.get(r.company);
    if (!cur || r.fy > cur.fy) last.set(r.company, r);
  }
  return [...last.values()].filter((r) => ok(r.price));
}

export interface SectorModelView {
  /** median of value ÷ price - 1 across the sector's companies */
  upside: number | null;
  /** median projected price move over a year */
  move: number | null;
  n: number;
}

export interface SectorForecast {
  sector: string;
  companies: number;
  byModel: Record<string, SectorModelView>;
  /** median across models */
  consensusUpside: number | null;
  consensusMove: number | null;
  /** companies whose model consensus sits above / near / below the price */
  below: number;
  near: number;
  above: number;
  /** each company with its consensus upside and projected move, best first */
  names: { company: string; upside: number; move: number | null }[];
}

const NEAR = 0.15;

/** What every model says each sector is worth today, and where it projects prices a year out. */
export function sectorForecasts(rows: ValuationRow[], models: string[], skills?: Record<string, ModelSkill>): SectorForecast[] {
  const sk = skills ?? learnSkills(rows, models);
  const latest = latestRows(rows);
  const sectors = new Map<string, ValuationRow[]>();
  for (const r of latest) (sectors.get(r.sector || "Unclassified") ?? sectors.set(r.sector || "Unclassified", []).get(r.sector || "Unclassified")!).push(r);
  const move = (m: string, v: number, p: number) => Math.exp((sk[m]?.beta ?? 0) * Math.log(v / p)) - 1;
  return [...sectors.entries()].map(([sector, list]) => {
    const byModel: Record<string, SectorModelView> = {};
    for (const m of models) {
      const ups: number[] = [], mv: number[] = [];
      for (const r of list) {
        const v = r.values?.[m];
        if (!ok(v) || !ok(r.price)) continue;
        ups.push(v / r.price - 1);
        if (sk[m]) mv.push(move(m, v, r.price));
      }
      byModel[m] = { upside: median(ups), move: median(mv), n: ups.length };
    }
    const names = list.map((r) => {
      const ups = models.map((m) => r.values?.[m]).filter(ok).map((v) => v / r.price! - 1);
      const mv = models.filter((m) => ok(r.values?.[m]) && sk[m]).map((m) => move(m, r.values[m] as number, r.price!));
      return { company: r.company, upside: median(ups), move: median(mv) };
    }).filter((x): x is { company: string; upside: number; move: number | null } => isNum(x.upside)).sort((a, b) => b.upside - a.upside);
    const ups = Object.values(byModel).map((x) => x.upside).filter(isNum) as number[];
    const mvs = Object.values(byModel).map((x) => x.move).filter(isNum) as number[];
    return {
      sector, companies: list.length, byModel, consensusUpside: median(ups), consensusMove: median(mvs),
      below: names.filter((x) => x.upside > NEAR).length, near: names.filter((x) => Math.abs(x.upside) <= NEAR).length,
      above: names.filter((x) => x.upside < -NEAR).length, names,
    };
  }).sort((a, b) => (b.consensusUpside ?? -9) - (a.consensusUpside ?? -9));
}

export const NEAR_BAND = NEAR;
export { metricName };
