// Notification preferences (kept in this browser) and dismissed research alerts.
import { useEffect, useState } from "react";
import { EVENTS, EventId, playPreset } from "./sound";

export interface EventSound { on: boolean; preset: string; volume: number }
export interface NotifyPrefs {
  /** master switch: badge, pop-ups and sounds */
  enabled: boolean;
  /** all sounds, and their overall volume */
  sound: boolean;
  volume: number;
  /** each event's own cue */
  events: Record<EventId, EventSound>;
  /** no sounds between these times (24-hour, this computer's clock) */
  quiet: { on: boolean; from: string; to: string };
  /** Windows / browser pop-ups when the tab is in the background */
  desktop: boolean;
  /** count research red flags and changes in the badge */
  research: boolean;
}

const KEY = "intval.notify.v2";
const DISMISSED = "intval.dismissed.v1";

export const defaultEvents = () =>
  Object.fromEntries(EVENTS.map((e) => [e.id, { on: true, preset: e.preset, volume: e.id === "ui" ? 0.5 : 0.8 }])) as Record<EventId, EventSound>;
export const DEFAULTS: NotifyPrefs = {
  enabled: true, sound: true, volume: 0.7, events: defaultEvents(), quiet: { on: false, from: "22:00", to: "07:00" }, desktop: false, research: true,
};

export function getPrefs(): NotifyPrefs {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || localStorage.getItem("intval.notify.v1") || "{}");
    return { ...DEFAULTS, ...raw, events: { ...defaultEvents(), ...(raw.events || {}) }, quiet: { ...DEFAULTS.quiet, ...(raw.quiet || {}) } };
  } catch {
    return DEFAULTS;
  }
}

export function setPrefs(patch: Partial<NotifyPrefs>) {
  const n = { ...getPrefs(), ...patch };
  try { localStorage.setItem(KEY, JSON.stringify(n)); } catch { /* private mode */ }
  window.dispatchEvent(new CustomEvent("notifyprefs"));
  return n;
}

export function setEvent(id: EventId, patch: Partial<EventSound>) {
  const p = getPrefs();
  return setPrefs({ events: { ...p.events, [id]: { ...p.events[id], ...patch } } });
}

export function resetPrefs() {
  try { localStorage.removeItem(KEY); localStorage.removeItem("intval.notify.v1"); } catch { /* private mode */ }
  window.dispatchEvent(new CustomEvent("notifyprefs"));
}

export function useNotifyPrefs(): NotifyPrefs {
  const [p, setP] = useState(getPrefs);
  useEffect(() => {
    const on = () => setP(getPrefs());
    window.addEventListener("notifyprefs", on);
    window.addEventListener("storage", on);
    return () => { window.removeEventListener("notifyprefs", on); window.removeEventListener("storage", on); };
  }, []);
  return p;
}

export function inQuietHours(q: NotifyPrefs["quiet"], now = new Date()) {
  if (!q.on) return false;
  const m = now.getHours() * 60 + now.getMinutes();
  const [fh, fm] = q.from.split(":").map(Number), [th, tm] = q.to.split(":").map(Number);
  const a = fh * 60 + fm, b = th * 60 + tm;
  return a <= b ? m >= a && m < b : m >= a || m < b;  // a window can cross midnight
}

/** Play an event's cue if notifications, sounds and that event are on (and it is not quiet hours). */
export function chime(id: EventId, force = false) {
  const p = getPrefs();
  const e = p.events[id];
  if (!e) return;
  if (force) return playPreset(e.preset, e.volume * p.volume || 0.5);
  if (!p.enabled || !p.sound || !e.on || inQuietHours(p.quiet)) return;
  playPreset(e.preset, e.volume * p.volume);
}

/** Show an operating-system notification when allowed and the page is hidden. */
export function desktop(title: string, body: string, tag?: string) {
  const p = getPrefs();
  if (!p.enabled || !p.desktop || typeof Notification === "undefined" || Notification.permission !== "granted") return;
  if (document.visibilityState === "visible") return;
  try { new Notification(title, { body, tag, silent: true }); } catch { /* not supported here */ }
}

// research alerts come from the latest research run; dismissing one hides it in this browser
export function getDismissed(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(DISMISSED) || "[]")); } catch { return new Set(); }
}

export function dismiss(keys: string[]) {
  const s = getDismissed();
  keys.forEach((k) => s.add(k));
  try { localStorage.setItem(DISMISSED, JSON.stringify([...s].slice(-3000))); } catch { /* private mode */ }
  window.dispatchEvent(new CustomEvent("notifyprefs"));
}

export function useDismissed(): Set<string> {
  const [s, setS] = useState(getDismissed);
  useEffect(() => {
    const on = () => setS(getDismissed());
    window.addEventListener("notifyprefs", on);
    return () => window.removeEventListener("notifyprefs", on);
  }, []);
  return s;
}
