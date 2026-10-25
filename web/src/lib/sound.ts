// Notification sounds, synthesised with the Web Audio API: no files to load.
// The palette is deliberately quiet and short - soft sine and glass tones
// with a gentle attack, a little low-passed and with a faint room reflection -
// the kind of cue a trading desk can live with all day.
//
// Browsers allow sound only after the person has clicked or typed on the
// page, so the audio context starts on the first interaction.

export interface Voice { f: number; at: number; dur: number; gain?: number; type?: OscillatorType; to?: number; attack?: number }
export interface Preset { label: string; hint: string; voices: Voice[]; room?: number }

const N = { F3: 174.61, A3: 220, C5: 523.25, E5: 659.25, G5: 783.99, A5: 880, C6: 1046.5, E6: 1318.5, G6: 1568, A6: 1760 };

export const PRESETS: Record<string, Preset> = {
  glass: { label: "Glass", hint: "one clear, soft tone", room: 0.22, voices: [{ f: N.G6, at: 0, dur: 0.42 }, { f: N.G6 * 2, at: 0, dur: 0.18, gain: 0.08 }] },
  rise: { label: "Rise", hint: "two notes up - something good", room: 0.16, voices: [{ f: N.A5, at: 0, dur: 0.22 }, { f: N.C6 * 1.0, at: 0.085, dur: 0.34 }] },
  fall: { label: "Fall", hint: "two notes down - worth a look", room: 0.16, voices: [{ f: N.C6, at: 0, dur: 0.22 }, { f: N.A5, at: 0.085, dur: 0.34 }] },
  pulse: { label: "Pulse", hint: "a double tap for attention", voices: [{ f: N.A5, at: 0, dur: 0.11, type: "triangle" }, { f: N.A5, at: 0.13, dur: 0.14, type: "triangle" }] },
  bloom: { label: "Bloom", hint: "a soft rising sweep", room: 0.2, voices: [{ f: 620, to: 930, at: 0, dur: 0.38, attack: 0.05 }] },
  chord: { label: "Chord", hint: "a gentle major chord - done", room: 0.25, voices: [{ f: N.C5, at: 0, dur: 0.7, gain: 0.7 }, { f: N.E5, at: 0.03, dur: 0.66, gain: 0.6 }, { f: N.G5, at: 0.06, dur: 0.62, gain: 0.55 }] },
  low: { label: "Low", hint: "a muted low tone - something failed", voices: [{ f: N.A3, at: 0, dur: 0.28, type: "triangle" }, { f: N.F3, at: 0.14, dur: 0.36, type: "triangle" }] },
  tick: { label: "Tick", hint: "a barely-there click", voices: [{ f: N.A6, at: 0, dur: 0.04, gain: 0.5 }] },
  marimba: { label: "Marimba", hint: "a warm wooden knock", voices: [{ f: N.E5, at: 0, dur: 0.2, type: "triangle", attack: 0.002 }, { f: N.E6, at: 0, dur: 0.07, gain: 0.25 }] },
  none: { label: "Silent", hint: "no sound", voices: [] },
};

let ctx: AudioContext | null = null;
function audio(): AudioContext | null {
  if (!ctx) {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
  }
  if (ctx.state === "suspended") ctx.resume().catch(() => undefined);
  return ctx;
}
if (typeof window !== "undefined") {
  const unlock = () => { audio(); window.removeEventListener("pointerdown", unlock); window.removeEventListener("keydown", unlock); };
  window.addEventListener("pointerdown", unlock);
  window.addEventListener("keydown", unlock);
}

export function playPreset(name: string, volume = 0.6) {
  const p = PRESETS[name];
  const c = audio();
  if (!p || !p.voices.length || !c || volume <= 0) return;
  const t0 = c.currentTime + 0.015;
  const out = c.createGain();
  out.gain.value = Math.min(1, volume) * 0.32;
  const lp = c.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 5200;
  lp.Q.value = 0.5;
  out.connect(lp).connect(c.destination);
  if (p.room) {  // one soft reflection: air, not echo
    const d = c.createDelay(0.5), fb = c.createGain(), wet = c.createGain();
    d.delayTime.value = 0.085;
    fb.gain.value = 0.22;
    wet.gain.value = p.room;
    out.connect(d);
    d.connect(fb).connect(d);
    d.connect(wet).connect(lp);
  }
  for (const v of p.voices) {
    const o = c.createOscillator(), g = c.createGain();
    o.type = v.type ?? "sine";
    o.frequency.setValueAtTime(v.f, t0 + v.at);
    if (v.to) o.frequency.exponentialRampToValueAtTime(v.to, t0 + v.at + v.dur * 0.8);
    const a = v.attack ?? 0.008, lvl = v.gain ?? 1;
    g.gain.setValueAtTime(0.0001, t0 + v.at);
    g.gain.exponentialRampToValueAtTime(lvl, t0 + v.at + a);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + v.at + v.dur);
    o.connect(g).connect(out);
    o.start(t0 + v.at);
    o.stop(t0 + v.at + v.dur + 0.05);
  }
}

/** Every event that can make a sound, with its default cue. */
export const EVENTS = [
  { id: "buy_below", label: "Below buy-below", desc: "A tracked company falls under its HYBRID MODEL buy-below price", preset: "rise" },
  { id: "below", label: "Fell to your alert", desc: "A tracked price reaches your lower alert level", preset: "fall" },
  { id: "above", label: "Rose to your alert", desc: "A tracked price reaches your upper alert level", preset: "bloom" },
  { id: "move", label: "Big daily move", desc: "A tracked company moves more than your daily-move limit", preset: "pulse" },
  { id: "job_done", label: "Run finished", desc: "A valuation, research or learning run completes", preset: "chord" },
  { id: "job_failed", label: "Run failed", desc: "A run stops with an error", preset: "low" },
  { id: "agent_reply", label: "An agent replies", desc: "An agent answers you in the Research Room", preset: "glass" },
  { id: "ui", label: "Interface", desc: "Switching notifications, clearing and deleting", preset: "tick" },
] as const;
export type EventId = (typeof EVENTS)[number]["id"];

export const alertEvent = (kind: string): EventId => (kind === "buy_below" ? "buy_below" : kind === "above" ? "above" : kind === "below" ? "below" : "move");
