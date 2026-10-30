import { useCompanies } from "./hooks";
import { useWatchlists } from "./live";

/**
 * What a job works on - one list for every place that starts a job (Operations,
 * the Research button, the command palette, Run buttons), matching the server:
 * with no list named, a job takes every watchlist. The report list in
 * data/companies.csv is offered to valuation jobs only, and only when it has
 * companies; it is never a default.
 */
export const EVERY = "__every__";
export const REPORT = "__report__";

export interface Target { value: string; label: string; count: number; options: Record<string, unknown> }

export function useTargets(report = false) {
  const lib = useWatchlists();
  const companies = useCompanies();
  const lists = (lib.data?.lists ?? []).filter((l) => l.count > 0);
  const reportCount = companies.data?.length ?? 0;
  const all: Target[] = [
    { value: EVERY, label: "Every watchlist", count: lib.data?.tracked ?? 0, options: {} },
    ...lists.map((l) => ({ value: l.id, label: l.name, count: l.count, options: { watchlist: [l.id] } })),
    ...(report && reportCount ? [{ value: REPORT, label: "Report list (companies.csv)", count: reportCount, options: { report_list: true } }] : []),
  ];
  const find = (v: string | null | undefined) => all.find((t) => t.value === v) ?? all[0];
  const options = all.map((t) => ({
    value: t.value, label: t.label, hint: t.count,
    icon: t.value === EVERY ? "layers" : t.value === REPORT ? "table" : "eye",
    group: t.value === EVERY ? undefined : t.value === REPORT ? "Other" : "A watchlist",
  }));
  return { all, find, options, empty: !!lib.data && lists.length === 0 };
}
