// The research workforce: roster, messages and live status (see src/agents/comms.py).
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export type Role = "chief" | "lead" | "analyst" | "system";
export interface AgentInfo { key: string; callsign: string; team: string; role: Role; title: string; duty: string }
export interface Team { slug: string; name: string; color: string; channel: string; purpose: string }
export interface Channel { id: string; name: string; team: string; purpose: string; members: string[] }
export interface Roster {
  teams: Record<string, Team>;
  agents: AgentInfo[];
  channels: Channel[];
  sources: Record<string, { title: string; detail: string }>;
  inputs: Record<string, string[]>;
  consumes: Record<string, string[]>;
  user: { callsign: string; title: string; team: string; color: string };
  commands: { cmd: string; help: string }[];
}
export type Kind = "task" | "fetch" | "share" | "finding" | "request" | "reply" | "flag" | "review" | "summary" | "verdict" | "system" | "user";
export interface Msg {
  id: number; mid: string; run: number; ts: number; channel: string; sender: string; to: string | null;
  company: string | null; kind: Kind; text: string; data: Record<string, unknown>; refs: string[];
}
export interface AgentStatus { state: "idle" | "working" | "done" | "error" | "waiting"; companies: string[]; task: string; since: number; done: number; errors: number; sent: number; received: number; llm: number }
export interface Progress { total: number; done: number; saved: number; fetched: number; messages: number; mode: string; started: number; finished: number | null }
export interface RunInfo { id: number; started: string; finished: string | null; mode: string; companies: number; llm_calls: number; note?: string; messages?: number }
export interface Live { run: RunInfo | null; active: boolean; progress: Progress | null; status: Record<string, AgentStatus>; messages: Msg[]; last_id: number }

export const KIND_META: Record<Kind, { label: string; color: string; icon: string }> = {
  task: { label: "Task", color: "#9CDCFE", icon: "checklist" },
  fetch: { label: "Fetch", color: "#57A3F8", icon: "cloud-download" },
  share: { label: "Shared", color: "#4EC9B0", icon: "references" },
  finding: { label: "Finding", color: "#86CF86", icon: "lightbulb" },
  request: { label: "Request", color: "#F0A35E", icon: "question" },
  reply: { label: "Reply", color: "#E0B97F", icon: "reply" },
  flag: { label: "Red flag", color: "#EF8773", icon: "warning" },
  review: { label: "Review", color: "#C586C0", icon: "law" },
  summary: { label: "Team report", color: "#AD80D7", icon: "git-merge" },
  verdict: { label: "Verdict", color: "#E0B97F", icon: "verified" },
  system: { label: "System", color: "#9A9B9C", icon: "server-process" },
  user: { label: "You", color: "#C9CBCD", icon: "account" },
};

export const useRoster = () => useQuery({ queryKey: ["agents-roster"], queryFn: () => api.get<Roster>("/api/agents/roster"), staleTime: Infinity });
export const useAgentRuns = () => useQuery({ queryKey: ["agents-runs"], queryFn: () => api.get<RunInfo[]>("/api/agents/runs"), refetchInterval: 15_000 });
export const useChannelStats = (run: number | null) =>
  useQuery({ queryKey: ["agents-channels", run], queryFn: () => api.get<{ run: number | null; channels: Record<string, { count: number; last: number; ts: number }> }>(`/api/agents/channels${run ? `?run=${run}` : ""}`), refetchInterval: 4000 });

/**
 * Live feed: polls /api/agents/live for new messages after the last id it has
 * seen, quickly while a run is active and slowly otherwise. Keeps a window of
 * recent messages and the latest status for every agent.
 */
export function useLiveFeed(run: number | null, keep = 4000) {
  const [state, setState] = useState<{ live: Live | null; messages: Msg[]; error: unknown }>({ live: null, messages: [], error: null });
  const last = useRef(0);
  const runRef = useRef<number | null>(run);
  useEffect(() => {
    runRef.current = run;
    last.current = 0;
    setState({ live: null, messages: [], error: null });
    let stop = false;
    let timer = 0;
    const tick = async () => {
      try {
        const q = new URLSearchParams({ after: String(last.current) });
        if (runRef.current) q.set("run", String(runRef.current));
        const d = await api.get<Live>(`/api/agents/live?${q}`);
        if (stop) return;
        if (d.messages.length) last.current = d.messages[d.messages.length - 1].id;
        setState((s) => ({ live: d, error: null, messages: d.messages.length ? [...s.messages, ...d.messages].slice(-keep) : s.messages }));
        // a full backlog page means more is waiting: fetch it straight away
        timer = window.setTimeout(tick, d.messages.length >= 600 ? 50 : d.active ? 1200 : 6000);
      } catch (e) {
        if (stop) return;
        setState((s) => ({ ...s, error: e }));
        timer = window.setTimeout(tick, 5000);
      }
    };
    tick();
    return () => { stop = true; window.clearTimeout(timer); };
  }, [run, keep]);
  return state;
}

export function teamOf(r: Roster | undefined, cs: string): Team | undefined {
  if (!r) return undefined;
  const a = r.agents.find((x) => x.callsign === cs);
  return a ? r.teams[a.team] : cs === "YOU" ? { slug: "you", name: "You", color: r.user.color, channel: "", purpose: "" } : undefined;
}
export const agentOf = (r: Roster | undefined, cs: string) => r?.agents.find((a) => a.callsign === cs);
export const colorOf = (r: Roster | undefined, cs: string) => teamOf(r, cs)?.color ?? "#9A9B9C";

export function dmName(id: string, me = "YOU") {
  const parts = id.replace(/^dm:/, "").split("|");
  return parts.filter((p) => p !== me).join(" ↔ ") || parts.join(" ↔ ");
}
export const isDm = (id: string) => id.startsWith("dm:");
export const dmId = (a: string, b: string) => "dm:" + [a, b].sort().join("|");

export function timeOf(ts: number) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

/** Head-count of the research workforce: the run orchestrator (OPS) is plumbing, not a researcher. */
export function workforceSize(r: Roster) {
  return { agents: r.agents.filter((a) => a.role !== "system").length, teams: Object.keys(r.teams).filter((t) => t !== "OPS").length };
}
export const roleName = (role: Role) => (role === "chief" ? "Chief" : role === "lead" ? "Team lead" : role === "system" ? "Orchestrator" : "Analyst");

// ---------------------------------------------------------------- per-agent tuning (src/agents/profiles.py)
export type Stance = "cautious" | "balanced" | "bold";
export type LlmMode = "auto" | "fast" | "smart" | "off";
export interface AgentProfileSettings { enabled: boolean; weight: number; llm: LlmMode; stance: Stance; min_confidence: number; rerun_quick: boolean; instructions: string }
export interface Profiles { profiles: Record<string, AgentProfileSettings>; default: AgentProfileSettings; llm_modes: LlmMode[]; stances: Stance[] }
export const useProfiles = () => useQuery({ queryKey: ["agent-profiles"], queryFn: () => api.get<Profiles>("/api/agents/profiles"), staleTime: 5_000 });
/** fields that differ from the defaults - shown as a "tuned" marker */
export function tuned(p: AgentProfileSettings | undefined, d: AgentProfileSettings | undefined) {
  if (!p || !d) return [] as string[];
  return (Object.keys(d) as (keyof AgentProfileSettings)[]).filter((k) => p[k] !== d[k]);
}
