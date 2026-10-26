import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  AgentSettings,
  Company,
  CsvRow,
  Download,
  HistoryPoint,
  IntelLatest,
  JobSummary,
  LabCompany,
  Metrics,
  ModelInfo,
  ProvidersInfo,
  RunPrefs,
  Status,
  Valuation,
} from "./api";

export const useStatus = () =>
  useQuery({ queryKey: ["status"], queryFn: () => api.get<Status>("/api/status"), refetchInterval: 3000 });

export const useIntel = () => useQuery({ queryKey: ["intel"], queryFn: () => api.get<IntelLatest>("/api/intel/latest") });

export const useHistory = (company: string) =>
  useQuery({
    queryKey: ["history", company],
    queryFn: () => api.get<HistoryPoint[]>(`/api/intel/history?company=${encodeURIComponent(company)}`),
    enabled: !!company,
  });

export const useValuation = () => useQuery({ queryKey: ["valuation"], queryFn: () => api.get<Valuation>("/api/valuation") });

export const useEnsemble = () =>
  useQuery({ queryKey: ["ensemble"], queryFn: () => api.get<{ available: boolean; rows: CsvRow[] }>("/api/valuation/ensemble") });

export const useHybridDetail = () =>
  useQuery({
    queryKey: ["hybrid-detail"],
    queryFn: () => api.get<{ available: boolean; rows: CsvRow[]; updated: number | null }>("/api/valuation/hybrid-model"),
  });

export const useMetrics = () => useQuery({ queryKey: ["metrics"], queryFn: () => api.get<Metrics>("/api/valuation/metrics") });

export const useExcluded = () =>
  useQuery({ queryKey: ["excluded"], queryFn: () => api.get<{ rows: Record<string, string>[] }>("/api/valuation/excluded") });

export const useCharts = () => useQuery({ queryKey: ["charts"], queryFn: () => api.get<string[]>("/api/charts") });

export const useDownloads = () => useQuery({ queryKey: ["downloads"], queryFn: () => api.get<Download[]>("/api/downloads") });

export const useCompanies = () => useQuery({ queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies") });

export const useJobs = (live: boolean) =>
  useQuery({ queryKey: ["jobs"], queryFn: () => api.get<JobSummary[]>("/api/jobs"), refetchInterval: live ? 2000 : 10000 });

export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => api.get<AgentSettings>("/api/settings/agents") });

export const useKeys = () => useQuery({ queryKey: ["keys"], queryFn: () => api.get<Record<string, boolean>>("/api/settings/keys") });

export const usePrefs = () =>
  useQuery({
    queryKey: ["prefs"],
    queryFn: () => api.get<{ values: RunPrefs; defaults: RunPrefs; latest_fy: number; min_fy: number }>("/api/run-preferences"),
  });

export const useModels = () => useQuery({ queryKey: ["models"], queryFn: () => api.get<ModelInfo[]>("/api/models"), staleTime: Infinity });

export const useProviders = () =>
  useQuery({
    queryKey: ["providers"],
    queryFn: () => api.get<ProvidersInfo>("/api/llm/providers"),
  });

export interface Tick {
  name: string;
  ticker: string;
  last: number | null;
  date: string;
  chg_1m: number | null;
  chg_1y: number | null;
}

export const useMarket = () =>
  useQuery({ queryKey: ["market"], queryFn: () => api.get<Tick[]>("/api/market"), staleTime: 300_000, refetchInterval: 600_000, retry: 0 });

export const useLabCompanies = () =>
  useQuery({ queryKey: ["lab-companies"], queryFn: () => api.get<LabCompany[]>("/api/hybrid/companies") });

export function useStartJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { kind: string; options?: Record<string, unknown> }) =>
      api.post<JobSummary>("/api/jobs", { kind: v.kind, options: v.options ?? {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });
}

/** After a job finishes, every result view should re-read the disk. */
export function useRefreshResults() {
  const qc = useQueryClient();
  return () => {
    for (const k of [
      "intel", "valuation", "ensemble", "hybrid-detail", "metrics", "excluded", "charts", "downloads",
      "history", "status", "jobs", "lab-companies",
    ]) {
      qc.invalidateQueries({ queryKey: [k] });
    }
  };
}
