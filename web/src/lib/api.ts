// Typed client for the Python API in server/app.py.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the local server. Is 'python run.py --web' still running?");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data
        ? (data as { detail: unknown }).detail
        : typeof data === "string" && data
          ? data
          : res.statusText;
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data as T;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  put: <T>(url: string, body: unknown) => request<T>("PUT", url, body),
  patch: <T>(url: string, body: unknown) => request<T>("PATCH", url, body),
  del: <T>(url: string) => request<T>("DELETE", url),
};

// ------------------------------------------------------------------ types
export type Num = number | null;
export type Dict<T = Num> = Record<string, T>;

export interface Status {
  project: string;
  python: string;
  valuation_updated: Num;
  intel_updated: Num;
  companies: number;
  keys: Record<string, boolean>;
  active_job: JobSummary | null;
  server_time: number;
}

export interface Evidence {
  id: string;
  source: string;
  title: string;
  url?: string;
  date?: string;
}

export interface AnalystRow {
  agent: string;
  lead: string;
  score: number;
  confidence: number;
  status: "ok" | "no_data" | "error";
  validated: boolean | null;
  summary: string;
  used_llm: boolean;
  flags: string[];
  notes: string[];
  evidence: Evidence[];
}

export interface LeadReport {
  lead: string;
  name: string;
  score: number;
  confidence: number;
  analysts: number;
  usable: number;
  summary: string;
}

export interface Claim {
  text: string;
  evidence: string[];
}

export interface Case {
  thesis: string;
  claims: Claim[];
  invalidated_if: string;
}

export interface Gate {
  pvgo_share: number;
  allowed: number;
  before: number;
  after: number;
}

/** One HYBRID MODEL evaluation (src/hybrid_model.py -> evaluate). */
export interface HMResult {
  value: Num;
  low: Num;
  high: Num;
  base_value: Num;
  bull_value: Num;
  bear_value: Num;
  probabilities: { bull: number; base: number; bear: number };
  confidence: number;
  confidence_parts: Dict;
  model_confidence?: number;
  sigma?: number;
  buy_below: Num;
  margin_of_safety: number;
  label: string;
  price: Num;
  upside: Num;
  cost_of_equity: number;
  cost_of_equity_capm: number;
  premia: Dict<number>;
  growth: number;
  growth_base: number;
  growth_terminal: number;
  growth_tilts: Dict<number>;
  lenses?: Dict;
  lens_weights?: Dict<number>;
  lenses_dropped?: string[];
  lenses_applicable?: string[];
  lens_calibration?: Dict<number>;
  gate?: Gate | null;
  core_value?: Num;
  quality_multiplier: number;
  quality_terms: Dict<number>;
  governance_haircut: number;
  red_flag_count: number;
  regime: string | null;
  waterfall: { step: string; value: Num; note: string }[];
}

export interface Verdict extends HMResult {
  model?: string;
  company: string;
  ticker: string;
  sector: string;
  expected_value: Num;
  valuation_fy: Num;
  research_score: number;
  leads: LeadReport[];
  red_flags: string[];
  risks: Dict<number>;
  tilts: Dict<number>;
  quality: Dict<number>;
  overlay: number;
  bull_case: Case | null;
  bear_case: Case | null;
  analysts: AnalystRow[];
  summary: { headline: string; note: string; key_points: Claim[]; watch_next: string[]; by: string };
  changes: string[];
}

export interface IntelMeta {
  run_id: number;
  mode: string;
  started: string;
  seconds: number;
  llm: { calls: number; cache_hits: number; by_provider: Dict<number>; failures: Dict<number> };
  llm_mode: string;
  feed_problems: string[];
  companies: number;
}

export interface IntelLatest {
  available: boolean;
  meta: IntelMeta | null;
  verdicts: Verdict[];
  error?: string;
}

export interface HistoryPoint {
  run: number;
  date: string;
  label: string;
  value: Num;
  price: Num;
  confidence: Num;
  mode: string;
}

export interface ValuationRow {
  company: string;
  sector: string;
  fy: string;
  price: Num;
  values: Dict;
}

export interface Valuation {
  available: boolean;
  models: string[];
  rows: ValuationRow[];
  updated: Num;
}

export type CsvRow = Record<string, string | number | null>;

export interface Metrics {
  overall: CsvRow[];
  by_year: CsvRow[];
  by_sector: CsvRow[];
  by_company: CsvRow[];
  win_rate: CsvRow[];
  feature_importance: CsvRow[];
  auto_train: CsvRow[];
  summary: Record<string, unknown>;
  updated: Num;
}

export interface Company {
  name: string;
  sector: string;
  cap: string;
  ticker: string;
}

export interface JobSummary {
  id: string;
  kind: string;
  args: string[];
  opts: Record<string, unknown> | null;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";
  started: number;
  finished: Num;
  returncode: Num;
  lines: number;
  controllable?: boolean;
}

export interface JobDetail extends JobSummary {
  since: number;
  new_lines: string[];
}

export interface AgentSettings {
  text: string;
  data: Record<string, unknown>;
  error: string | null;
  updated: Num;
}

export interface Download {
  key: string;
  file: string;
  updated: number;
  size: number;
}

export interface ParamDef {
  path: string;
  label: string;
  kind: "pct" | "num" | "int" | "bool";
  min: number;
  max: number;
  desc: string | null;
  value: number | boolean | null;
  in_file: boolean;
}

export interface ParamGroup {
  group: string;
  params: ParamDef[];
}

export interface LabCompany {
  company: string;
  sector: string;
  ticker: string;
  source: "research" | "report";
  price: Num;
  value: Num;
  label: string;
  confidence: number;
  regime: string | null;
  fy: Num;
}

export interface Simulation {
  company: string;
  source: "research" | "report";
  fy: Num;
  saved: HMResult;
  live: HMResult;
  inputs: Record<string, number | string | null>;
  sensitivity?: { path: string; step: number; down: Num; up: Num }[];
}

export interface PortfolioRow {
  company: string;
  sector: string;
  price: Num;
  saved: Num;
  live: Num;
  saved_label: string;
  live_label: string;
  confidence: number;
}

export interface RunPrefs {
  models: Record<string, boolean>;
  ml_enabled: boolean;
  ml_split: string;
  estimation: string;
  screening: string;
  min_complete_fy: number;
  min_benchmark_fy: number;
  auto_relax: boolean;
  keep_in_peers: boolean;
  keep_in_ml: boolean;
  require_price: boolean;
  audit_all: boolean;
  benchmark_basis: string;
  bench_offset_days: number;
  mean_basis: string;
  exchange: string;
  analyze: boolean;
  dpi: number;
  fy_labels: string;
  reasons: string;
  overrides: boolean;
  start_year: number;
  end_year: number;
}

export interface ModelInfo {
  key: string;
  name: string;
  kind: string;
  blurb: string;
}

export interface Provider {
  name: string;
  base_url: string;
  key_env: string;
  has_key: boolean;
  models: Record<string, string>;
  limits: Record<string, number | null>;
}

export interface ModelTestResult {
  ok: boolean;
  status: number | null;
  seconds: number;
  reply?: string;
  error?: string | null;
}
