// Live market, watchlist and learning: types and query hooks.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface MarketStatus {
  state: "open" | "pre-open" | "closed";
  ist: string;
  next_open: number;
  closes_at: number | null;
  source: string;
  delay_note: string;
}

export interface LiveHM {
  company: string;
  value: number | null;
  low: number | null;
  high: number | null;
  buy_below: number | null;
  label: string;
  upside: number | null;
  confidence: number | null;
  fy: number | null;
  source: "report" | "research";
}

export interface IndexQuote {
  name: string;
  ticker: string;
  last: number | null;
  prev: number | null;
  chg_pct: number | null;
  t: number;
  spark: (number | null)[];
  month: (number | null)[];
}

export interface Meta {
  ticker: string;
  name: string;
  sector: string;
  cap: string;
  lists: string[];
  lookup?: boolean;
}

export interface ScanRow extends Meta {
  last: number;
  prev: number;
  chg: number;
  chg_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number;
  avg_volume: number | null;
  vol_ratio: number | null;
  turnover: number;
  hi_52: number;
  lo_52: number;
  from_hi: number | null;
  from_lo: number | null;
  ret_1w: number | null;
  ret_1m: number | null;
  ret_3m: number | null;
  ret_1y: number | null;
  rsi: number | null;
  date: string;
  spark: (number | null)[];
  hm?: LiveHM;
}

export interface Bar { t: number; o: number | null; h: number | null; l: number | null; c: number | null; v: number }

export interface ChartData {
  ticker: string;
  range: string;
  interval: string;
  bars: Bar[];
  last: number | null;
  prev_close: number | null;
  chg_pct: number | null;
  meta: Meta;
  hm: LiveHM | null;
  tracked: boolean;
  market: MarketStatus;
  stored?: number;
}

export interface Quote {
  ticker: string;
  last?: number;
  t?: number;
  session?: string;
  prev_close?: number | null;
  chg?: number | null;
  chg_pct?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  volume?: number;
  polled: number;
  spark?: (number | null)[];
  month?: (number | null)[];
  hi_3m?: number | null;
  lo_3m?: number | null;
  stale?: boolean;
  hm?: LiveHM | null;
  error?: string;
}

export interface WatchItem {
  ticker: string;
  name: string;
  sector: string;
  cap: string;
  added: number;
  added_price: number | null;
  alert_below: number | null;
  alert_above: number | null;
  note: string;
  quote: Quote | null;
  since_added: number | null;
}

export interface TrackerSettings { paused: boolean; poll_open: number; poll_closed: number; move_alert: number; retention_days: number }

export interface TrackerState {
  running: boolean;
  paused: boolean;
  interval: number;
  last_poll: number | null;
  next_poll: number | null;
  error: string | null;
  polls: number;
  settings: TrackerSettings;
  market: MarketStatus;
  stored_bars: number | null;
}

export interface LiveAlert {
  id: number;
  t: number;
  ticker: string;
  name: string;
  kind: "below" | "above" | "buy_below" | "move";
  message: string;
  price: number;
  level: number;
  session: string;
  seen: number;
}

export interface LearningMetrics {
  report?: number | null;
  hm_medape?: number | null;
  hm_hit20?: number | null;
  hm_n?: number | null;
  hm_confidence?: number | null;
  hm_confidence_all?: number | null;
  hm_fy?: string;
  ml_direction?: number | null;
  ml_train_rows?: number | null;
  labelled_rows?: number;
  training_companies?: number;
}

export interface LearningRun extends LearningMetrics {
  t: number;
  job: string;
  learning: boolean;
  auto_train: boolean;
}

export interface LearningSettings { use_in_runs: boolean; auto_feed: boolean; auto_retrain: boolean; feed_after: string; last_auto: string | null }

export interface LearningStatus {
  companies: number;
  by_list: Record<string, number>;
  sectors: number;
  by_sector: [string, number][];
  window: [number, number];
  cache: { fresh: number; stale: number; missing: number; cache_days: number };
  settings: LearningSettings;
  history: LearningRun[];
  current: LearningMetrics;
  valued: number;
}

export const isOpen = (m?: MarketStatus | null) => m?.state === "open" || m?.state === "pre-open";

export const useIndices = () =>
  useQuery({
    queryKey: ["live-indices"],
    queryFn: () => api.get<{ market: MarketStatus; indices: IndexQuote[]; sectors: IndexQuote[] }>("/api/live/indices"),
    refetchInterval: (q) => (isOpen(q.state.data?.market) ? 30_000 : 300_000),
    retry: 1,
  });

export const useScan = () =>
  useQuery({
    queryKey: ["live-scan"],
    queryFn: () => api.get<{ rows: ScanRow[]; as_of: number | null; scanning: boolean; error: string | null; seconds: number | null; market: MarketStatus }>("/api/live/scan"),
    refetchInterval: (q) => (q.state.data?.scanning || !q.state.data?.rows.length ? 2000 : isOpen(q.state.data?.market) ? 60_000 : 600_000),
  });

export const useChart = (ticker: string | null, range: string) =>
  useQuery({
    queryKey: ["live-chart", ticker, range],
    queryFn: () => api.get<ChartData>(`/api/live/chart?ticker=${encodeURIComponent(ticker!)}&range=${range}`),
    enabled: !!ticker,
    refetchInterval: (q) => (isOpen(q.state.data?.market) && (range === "1d" || range === "5d" || range === "tracked") ? 20_000 : false),
    retry: 0,
    placeholderData: (prev) => (prev && prev.ticker === ticker ? prev : undefined),
  });

export const useLiveSearch = (q: string) =>
  useQuery({
    queryKey: ["live-search", q],
    queryFn: () => api.get<Meta[]>(`/api/live/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length > 0,
    staleTime: 60_000,
  });

export const useSectors = () => useQuery({ queryKey: ["live-sectors"], queryFn: () => api.get<string[]>("/api/live/sectors"), staleTime: 600_000 });

export const useWatchlist = () =>
  useQuery({
    queryKey: ["watchlist"],
    queryFn: () => api.get<{ items: WatchItem[]; tracker: TrackerState }>("/api/watchlist"),
    refetchInterval: (q) => (isOpen(q.state.data?.tracker.market) ? 10_000 : 60_000),
  });

export const useLiveAlerts = () =>
  useQuery({ queryKey: ["live-alerts"], queryFn: () => api.get<LiveAlert[]>("/api/live/alerts"), refetchInterval: 30_000, retry: 0 });

export const useLearning = () =>
  useQuery({ queryKey: ["learning"], queryFn: () => api.get<LearningStatus>("/api/learning"), refetchInterval: 30_000 });

/** Add, change or remove watchlist entries; every change refreshes the list. */
export function useWatchMutations() {
  const qc = useQueryClient();
  const done = () => {
    qc.invalidateQueries({ queryKey: ["watchlist"] });
    qc.invalidateQueries({ queryKey: ["live-chart"] });
    qc.invalidateQueries({ queryKey: ["learning"] });
  };
  return {
    add: useMutation({ mutationFn: (m: { ticker: string; name?: string; sector?: string; cap?: string }) => api.post("/api/watchlist", m), onSuccess: done }),
    update: useMutation({ mutationFn: ({ ticker, ...patch }: { ticker: string } & Record<string, unknown>) => api.patch(`/api/watchlist/${encodeURIComponent(ticker)}`, patch), onSuccess: done }),
    remove: useMutation({ mutationFn: (ticker: string) => api.del(`/api/watchlist/${encodeURIComponent(ticker)}`), onSuccess: done }),
    tracker: useMutation({ mutationFn: (patch: Partial<TrackerSettings>) => api.put("/api/live/tracker", patch), onSuccess: done }),
    poll: useMutation({ mutationFn: () => api.post("/api/live/tracker/poll", {}), onSuccess: () => window.setTimeout(done, 2500) }),
  };
}
