// Where a company's full analysis lives now that Coverage is folded into the
// watchlists: /watchlist/<list>/<ticker> inside a list, /company/<name>
// anywhere else (the page finds the company's watchlist itself).
import { Verdict } from "./api";
import { normName } from "./scope";

export const bareTicker = (t: string | null | undefined) => (t ?? "").toUpperCase().split(".")[0];

/** The full analysis page of a researched company. */
export const companyPath = (company: string) => `/company/${encodeURIComponent(company)}`;
/** A company's page inside one watchlist (previous / next move through that list). */
export const listCompanyPath = (listId: string, ticker: string) => `/watchlist/${encodeURIComponent(listId)}/${encodeURIComponent(ticker)}`;

/** The research verdict for a watchlist company: same NSE symbol, or the same name. */
export function findVerdict(verdicts: Verdict[] | undefined, c: { ticker?: string | null; name?: string | null }): Verdict | null {
  if (!verdicts?.length) return null;
  const t = bareTicker(c.ticker);
  const n = normName(c.name);
  const byName = n ? verdicts.find((v) => normName(v.company) === n) : undefined;
  const byTicker = t ? verdicts.filter((v) => bareTicker(v.ticker) === t) : [];
  // two verdicts on one symbol (test data): the name decides
  return (byTicker.length > 1 ? byName ?? byTicker[0] : byTicker[0] ?? byName) ?? null;
}
