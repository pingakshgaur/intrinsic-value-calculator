// What the Agent Network shows (layers), how it is arranged, and what you
// added to it (links, notes). All of it stays in this browser.
import { useEffect, useState } from "react";
import { Arrange, Detail, GEdge, Pt } from "./agentGraph";

export type EdgeKind = GEdge["kind"];
export interface Layers {
  arrange: Arrange;
  detail: Detail;
  sources: boolean;      // data-source nodes and their edges
  outputs: boolean;      // verdicts / alerts / room nodes
  ops: boolean;          // the run orchestrator
  analysts: boolean;     // false = leads only (traffic re-routes to the lead)
  frames: boolean;       // team bands (hierarchy only)
  edges: Record<EdgeKind, boolean>;
  labels: boolean;       // edge captions
  packets: boolean;      // info-bits travelling the edges
  floats: boolean;       // score pop-ups over nodes
  minimap: boolean;
  annotations: boolean;  // your links and notes
}

export const DEFAULT_LAYERS: Layers = {
  arrange: "hierarchy", detail: "compact", sources: true, outputs: true, ops: false, analysts: true, frames: true,
  edges: { input: false, report: true, command: true, consume: false, output: true, ops: false },
  labels: false, packets: true, floats: false, minimap: false, annotations: true,
};

export const EDGE_NAME: Record<EdgeKind, string> = {
  input: "Data feeds", report: "Findings to leads", command: "Team reports to chief", consume: "Cross-team reads", output: "Verdicts out", ops: "Run control",
};

export interface View { name: string; layers: Layers; hidden: string[]; teamsOff: string[] }
/** Built-in starting points; your own saved views are listed after them. */
export const PRESETS: View[] = [
  { name: "Simple", layers: DEFAULT_LAYERS, hidden: [], teamsOff: [] },
  { name: "Leads only", layers: { ...DEFAULT_LAYERS, analysts: false, sources: false, frames: false }, hidden: [], teamsOff: [] },
  { name: "Data flow", layers: { ...DEFAULT_LAYERS, edges: { ...DEFAULT_LAYERS.edges, input: true, consume: true }, outputs: false }, hidden: [], teamsOff: [] },
  { name: "Everything", layers: { ...DEFAULT_LAYERS, detail: "full", ops: true, edges: { input: true, report: true, command: true, consume: true, output: true, ops: true }, labels: true, floats: true, minimap: true }, hidden: [], teamsOff: [] },
  { name: "Radial", layers: { ...DEFAULT_LAYERS, arrange: "radial", frames: false }, hidden: [], teamsOff: [] },
];

export interface Link { id: string; from: string; to: string; label: string }
export interface Note { id: string; x: number; y: number; text: string; arrange: Arrange; color?: NoteTone; at?: number }
export type NoteTone = "amber" | "blue" | "green" | "violet" | "red";
export const NOTE_TONES: { id: NoteTone; label: string; c: string }[] = [
  { id: "amber", label: "Amber", c: "#e0b97f" }, { id: "blue", label: "Blue", c: "#57a3f8" }, { id: "green", label: "Green", c: "#86cf86" },
  { id: "violet", label: "Violet", c: "#ad80d7" }, { id: "red", label: "Red", c: "#ef8773" },
];
export interface Mesh { links: Link[]; notes: Note[] }

function read<T>(k: string, d: T): T {
  try { const v = JSON.parse(localStorage.getItem(k) || "null"); return v ?? d; } catch { return d; }
}
function write(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } }

/** useState that persists to localStorage (merging new default fields into old saved objects). */
export function useStored<T>(key: string, init: T) {
  const [v, setV] = useState<T>(() => {
    const got = read<T>(key, init);
    return init && typeof init === "object" && !Array.isArray(init) ? { ...init, ...got } : got;
  });
  useEffect(() => write(key, v), [key, v]);
  return [v, setV] as const;
}

export const uid = () => Math.random().toString(36).slice(2, 9);
export type Positions = Record<string, Pt>;
export const posKey = (a: Arrange, d: Detail) => `net.pos.v2.${a}.${d}`;
