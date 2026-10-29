// Scope: the watchlist the app is looking at. "All companies" (null) is the
// app as it always was; choosing a watchlist narrows the Command Center,
// Model Performance and the research workforce to its
// companies. Kept in this browser.
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useWatchlists, WatchList } from "./live";

const KEY = "intval.scope.v1";

/** "Hindustan Aeronautics Limited" and "Hindustan Aeronautics Ltd." match */
export const normName = (s: string | null | undefined) =>
  (s ?? "").toLowerCase().replace(/\b(limited|ltd|ltd\.|inc|corp|corporation|co)\b\.?/g, "").replace(/[^a-z0-9]+/g, " ").trim();
const bare = (t: string | null | undefined) => (t ?? "").toUpperCase().split(".")[0];

export interface Scope {
  id: string | null;
  list: WatchList | null;
  lists: WatchList[];
  set: (id: string | null) => void;
  /** is this company in scope? (always true for "All companies") */
  has: (c: { ticker?: string | null; company?: string | null; name?: string | null }) => boolean;
  /** "IT ideas" or "All companies" */
  label: string;
}

const Ctx = createContext<Scope>({ id: null, list: null, lists: [], set: () => undefined, has: () => true, label: "All companies" });

export function ScopeProvider({ children }: { children: ReactNode }) {
  const q = useWatchlists();
  const [id, setId] = useState<string | null>(() => { try { return localStorage.getItem(KEY) || null; } catch { return null; } });
  const set = useCallback((v: string | null) => {
    setId(v);
    try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch { /* private mode */ }
  }, []);
  const lists = q.data?.lists ?? [];
  const list = id ? lists.find((l) => l.id === id) ?? null : null;
  // a deleted watchlist falls back to everything
  useEffect(() => { if (id && q.data && !list) set(null); }, [id, q.data, list, set]);
  const value = useMemo<Scope>(() => {
    if (!list) return { id: null, list: null, lists, set, has: () => true, label: "All companies" };
    const tickers = new Set(list.tickers.map(bare));
    const names = new Set(list.companies.map((c) => normName(c.name)).filter(Boolean));
    return {
      id: list.id, list, lists, set, label: list.name,
      has: (c) => (!!c.ticker && tickers.has(bare(c.ticker))) || (!!(c.company || c.name) && names.has(normName(c.company ?? c.name))),
    };
  }, [list, lists, set]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useScope = () => useContext(Ctx);
