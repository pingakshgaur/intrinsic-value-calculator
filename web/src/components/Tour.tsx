import { CSSProperties, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { useIntel } from "../lib/hooks";
import { slug } from "../lib/format";
import { CHAPTERS, TOUR_STEPS, TourCtx } from "../lib/tourSteps";
import { Icon } from "./ui";

// ---- progress, remembered in this browser -------------------------------

const KEY = "intval.tour.v1";
export interface TourProgress { idx: number; done: string[]; finished?: boolean }
export function loadTour(): TourProgress | null {
  try { const p = JSON.parse(localStorage.getItem(KEY) || "null"); return p && typeof p.idx === "number" ? p : null; } catch { return null; }
}
function saveTour(p: TourProgress) { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* storage blocked: progress is not kept */ } }

/** What the tour was asked to do: open on the welcome, jump to a chapter, or carry on. */
export interface TourStart { chapter?: number; resume?: boolean }

type Phase = "welcome" | "step" | "done";
interface Box { left: number; top: number; width: number; height: number }

const MINUTES = Math.max(4, Math.round(TOUR_STEPS.length * 0.14));
const PAD = 8;

/** Find a step's target: a CSS selector, or "panel:Title" for the panel with that heading. */
function findTarget(t: string): HTMLElement | null {
  if (t.startsWith("panel:")) {
    const title = t.slice(6);
    const h = [...document.querySelectorAll<HTMLElement>(".panel-h h3")].find((x) => x.textContent?.trim() === title);
    return (h?.closest(".panel") as HTMLElement | null) ?? null;
  }
  try { return document.querySelector<HTMLElement>(t); } catch { return null; }
}
const visible = (el: HTMLElement) => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
const sameBox = (a: Box | null, b: Box | null) => !!a && !!b && Math.abs(a.left - b.left) < 0.5 && Math.abs(a.top - b.top) < 0.5 && Math.abs(a.width - b.width) < 0.5 && Math.abs(a.height - b.height) < 0.5;

/**
 * The guided tour: a welcome, then a spotlight that glides from page to page
 * with a card explaining what it points at, then a send-off with next steps.
 * The page under the spotlight stays usable throughout.
 */
export function Tour({ start, onClose, openHelp }: { start: TourStart; onClose: () => void; openHelp: () => void }) {
  const nav = useNavigate();
  const intel = useIntel();
  const first = intel.data?.verdicts?.[0]?.company ?? null;
  const ctx: TourCtx = useMemo(() => ({ company: first ? slug(first) : null }), [first]);

  // steps whose page cannot open (no researched company yet) are left out
  const steps = useMemo(() => TOUR_STEPS.map((s, i) => ({ ...s, i })).filter((s) => {
    if (typeof s.route === "function") return s.route(ctx) != null;
    return true;
  }), [ctx]);

  const saved = useMemo(loadTour, []);
  const [phase, setPhase] = useState<Phase>(start.chapter != null || start.resume ? "step" : "welcome");
  const [idx, setIdx] = useState(() => {
    if (start.chapter != null) return Math.max(0, steps.findIndex((s) => s.chapter === start.chapter));
    if (start.resume && saved) return Math.min(saved.idx, steps.length - 1);
    return 0;
  });
  const [done, setDone] = useState<string[]>(() => saved?.done ?? []);
  const step = steps[Math.min(idx, steps.length - 1)];
  const chapter = CHAPTERS[step.chapter];
  const inChapter = steps.filter((s) => s.chapter === step.chapter);
  const posInChapter = inChapter.indexOf(step);

  // ---- open the step's page, find its target, follow it ----------------

  const [box, setBox] = useState<Box | null>(null);
  const [seeking, setSeeking] = useState(false);
  // why a target is not lit: not on the page at all, or there but hidden at this window size
  const [missing, setMissing] = useState<"absent" | "hidden" | null>(null);
  const el = useRef<HTMLElement | null>(null);
  const measure = useCallback(() => {
    const e = el.current;
    if (!e || !e.isConnected) { if (e) { el.current = null; setBox(null); } return; }
    const r = e.getBoundingClientRect();
    const b = { left: r.left, top: r.top, width: r.width, height: r.height };
    setBox((old) => (sameBox(old, b) ? old : b));
  }, []);

  const routeOf = useCallback((i: number) => {
    for (let j = i; j >= 0; j--) {
      const r = steps[j].route;
      if (r) return typeof r === "function" ? r(ctx) : r;
    }
    return null;
  }, [steps, ctx]);

  useEffect(() => {
    if (phase !== "step") return;
    el.current = null;
    const r = routeOf(idx);
    if (r && window.location.pathname + window.location.search !== r) nav(r);
    setMissing(null);
    if (!step.target) { setBox(null); setSeeking(false); return; }
    setSeeking(true);
    const t0 = performance.now();
    let timer = 0, stop = false;
    const look = () => {
      if (stop) return;
      const found = findTarget(step.target!);
      if (found && visible(found)) {
        el.current = found;
        const rr = found.getBoundingClientRect();
        // off screen: starting above the top, or too low to read (a tall target only needs its top in view)
        const off = (q: DOMRect) => q.top < 0 || q.top > window.innerHeight - 120 || (q.height < window.innerHeight * 0.85 && q.bottom > window.innerHeight - 8);
        if (off(rr)) {
          const block = rr.height > window.innerHeight * 0.7 ? "start" : "center";
          found.scrollIntoView({ block, behavior: "smooth" });
          // smooth scrolling can stall (a background tab, some settings): then jump
          timer = window.setTimeout(() => { if (!stop && off(found.getBoundingClientRect())) { found.scrollIntoView({ block }); measure(); } }, 700);
        }
        measure();
        setSeeking(false);
        return;
      }
      if (performance.now() - t0 > 5000) { setBox(null); setSeeking(false); setMissing(found ? "hidden" : "absent"); return; }
      timer = window.setTimeout(look, 120);
    };
    // let the new page render first
    timer = window.setTimeout(look, r ? 160 : 40);
    return () => { stop = true; window.clearTimeout(timer); };
  }, [phase, idx, step, routeOf, nav, measure]);

  useEffect(() => {
    if (phase !== "step") return;
    measure();
    const iv = window.setInterval(measure, 200);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => { window.clearInterval(iv); window.removeEventListener("resize", measure); window.removeEventListener("scroll", measure, true); };
  }, [phase, idx, measure]);

  // ---- moving through the tour -----------------------------------------

  useEffect(() => { if (phase === "step") saveTour({ idx, done }); }, [phase, idx, done]);

  const finishChapter = (c: number) => setDone((d) => (d.includes(CHAPTERS[c].id) ? d : [...d, CHAPTERS[c].id]));
  const go = (i: number) => {
    if (i >= steps.length) { finishChapter(step.chapter); setPhase("done"); saveTour({ idx: 0, done: CHAPTERS.map((c) => c.id), finished: true }); return; }
    if (steps[i].chapter !== step.chapter && i > idx) finishChapter(step.chapter);
    setIdx(Math.max(0, i));
    setPhase("step");
  };
  const next = () => go(idx + 1);
  const back = () => { if (idx > 0) go(idx - 1); };
  const skipChapter = () => { const n = steps.findIndex((s) => s.chapter > step.chapter); go(n < 0 ? steps.length : n); };
  const jumpChapter = (c: number) => { const n = steps.findIndex((s) => s.chapter === c); if (n >= 0) { setIdx(n); setPhase("step"); } };
  const restart = () => { setDone([]); setIdx(0); setPhase("welcome"); };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target;
      if (t instanceof HTMLElement && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (phase !== "step") { if (phase === "welcome" && e.key === "Enter") { e.preventDefault(); go(idx); } return; }
      if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); back(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ---- where the spotlight and card go ---------------------------------

  const card = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 380, h: 260 });
  useLayoutEffect(() => {
    const c = card.current;
    if (!c) return;
    const w = c.offsetWidth, h = c.offsetHeight;
    setSize((s) => (Math.abs(s.w - w) < 1 && Math.abs(s.h - h) < 1 ? s : { w, h }));
  });
  const vw = window.innerWidth, vh = window.innerHeight;
  const phone = vw < 640;
  const spot: Box | null = box ? (() => {
    const l = Math.max(4, box.left - PAD), t = Math.max(4, box.top - PAD);
    const r = Math.min(vw - 4, box.left + box.width + PAD), b = Math.min(vh - 4, box.top + box.height + PAD);
    return r - l > 4 && b - t > 4 ? { left: l, top: t, width: r - l, height: b - t } : null;
  })() : null;

  const place = (): CSSProperties => {
    if (phone) return {};
    const M = 16, G = 14, { w, h } = size;
    const clampX = (x: number) => Math.max(M, Math.min(vw - w - M, x));
    const clampY = (y: number) => Math.max(M, Math.min(vh - h - M, y));
    if (!spot) return { left: (vw - w) / 2, top: Math.max(M, (vh - h) / 2) };
    const midY = spot.top + spot.height / 2 - h / 2, midX = spot.left + spot.width / 2 - w / 2;
    const at = {
      right: { left: clampX(spot.left + spot.width + G), top: clampY(midY) },
      left: { left: clampX(spot.left - w - G), top: clampY(midY) },
      bottom: { left: clampX(midX), top: clampY(spot.top + spot.height + G) },
      top: { left: clampX(midX), top: clampY(spot.top - h - G) },
      // a target filling the screen: inside it, bottom right
      inside: { left: clampX(spot.left + spot.width - w - 24), top: clampY(spot.top + spot.height - h - 24) },
    };
    // how much of the target a position would cover
    const cover = (p: { left: number; top: number }) => Math.max(0, Math.min(p.left + w, spot.left + spot.width) - Math.max(p.left, spot.left)) * Math.max(0, Math.min(p.top + h, spot.top + spot.height) - Math.max(p.top, spot.top));
    const order = [...(step.side && step.side !== "auto" ? [step.side] : []), "right", "bottom", "left", "top"] as (keyof typeof at)[];
    const clear = order.find((k) => cover(at[k]) === 0);
    if (clear) return at[clear];
    // nothing is clear: the place that hides the least of it
    const keys = Object.keys(at) as (keyof typeof at)[];
    return at[keys.reduce((best, k) => (cover(at[k]) < cover(at[best]) ? k : best), "inside")];
  };

  // ---- render ----------------------------------------------------------

  const counts = CHAPTERS.map((_, c) => steps.filter((s) => s.chapter === c).length);
  const last = idx === steps.length - 1;
  const nextChapter = posInChapter === inChapter.length - 1 && !last ? CHAPTERS[steps[idx + 1].chapter] : null;

  return createPortal(
    <div className={`tour ${phase}`} role="dialog" aria-label="Onboarding tour">
      {phase === "step" && (
        <>
          <div className={`tour-spot ${spot ? "" : "none"}`} style={spot ?? { left: vw / 2, top: vh / 2, width: 0, height: 0 }}>
            {spot && <i className="tour-ring" style={{ ["--tc" as string]: chapter.color }} />}
          </div>
          <div ref={card} className={`tour-card ${phone ? "dock" : ""}`} style={{ ...place(), ["--tc" as string]: chapter.color }} key="card">
            <div className="tour-card-h">
              <span className="tour-chip"><Icon name={seeking ? "loading" : chapter.icon} className={`xs ${seeking ? "spin" : ""}`} />{chapter.title}</span>
              <span className="tour-count">{posInChapter + 1} / {inChapter.length}</span>
              <span className="spacer" />
              <button className="ibtn xs" onClick={onClose} title="Leave the tour (Esc)"><Icon name="close" className="xs" /></button>
            </div>
            <div className="tour-card-b" key={idx}>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
              {step.try && <div className="tour-try"><Icon name="lightbulb" className="xs" /><span>{step.try}</span></div>}
              {missing && <div className="tour-miss xs faint"><Icon name="eye-closed" className="xs" />{missing === "hidden" ? "Hidden at this window size: widen the window to see it." : "Not on this page right now: it appears once there is data for it."}</div>}
            </div>
            <div className="tour-prog" aria-hidden>
              {CHAPTERS.map((c, ci) => counts[ci] > 0 && (
                <button key={c.id} style={{ flex: counts[ci], ["--tc" as string]: c.color }} title={c.title} onClick={() => jumpChapter(ci)}
                  className={ci < step.chapter || done.includes(c.id) ? "full" : ci === step.chapter ? "cur" : ""}>
                  {ci === step.chapter && <i style={{ width: `${(100 * (posInChapter + 1)) / inChapter.length}%` }} />}
                </button>
              ))}
            </div>
            <div className="tour-card-f">
              <button className="btn sm ghost" onClick={back} disabled={idx === 0}><Icon name="arrow-left" className="xs" />Back</button>
              {!last && <button className="btn sm ghost" onClick={skipChapter} title="Jump to the next chapter">Skip chapter</button>}
              <span className="spacer" />
              <button className="btn sm tour-next" onClick={next}>
                {last ? "Finish" : nextChapter ? <>Next: {nextChapter.title}</> : "Next"}<Icon name={last ? "check" : "arrow-right"} className="xs" />
              </button>
            </div>
          </div>
        </>
      )}

      {phase === "welcome" && (
        <div className="tour-modal">
          <div className="tour-orbs" aria-hidden><i /><i /><i /></div>
          <div className="tour-hero">
            <button className="ibtn tour-x" onClick={onClose} title="Close (Esc)"><Icon name="close" /></button>
            <span className="tour-logo" aria-hidden><i /></span>
            <div className="tour-kicker">Onboarding</div>
            <h1>Welcome to INTVAL Workbench</h1>
            <p className="tour-lede">An intrinsic-value workbench for Indian equities. Classic and machine-learning valuation models, a HYBRID MODEL that blends them, and twenty-three AI research agents that check every company against the news, its filings and the market.</p>
            <div className="tour-pillars">
              <div><Icon name="symbol-operator" /><b>Value</b><span>Eleven models and the HYBRID MODEL, scored against real prices every year.</span></div>
              <div><Icon name="organization" /><b>Research</b><span>Agents that read, argue bull against bear, and cite every point.</span></div>
              <div><Icon name="eye" /><b>Track</b><span>Live prices, watchlists, alerts and per-model forecasts.</span></div>
            </div>
            <div className="tour-chapters">
              {CHAPTERS.map((c, ci) => counts[ci] > 0 && (
                <button key={c.id} style={{ ["--tc" as string]: c.color, animationDelay: `${120 + ci * 40}ms` }} onClick={() => jumpChapter(ci)} title={`Start at “${c.title}”`}>
                  <span className="ic"><Icon name={done.includes(c.id) ? "check" : c.icon} className="sm" /></span>
                  <span className="t"><b>{c.title}</b><span>{c.blurb}</span></span>
                  <span className="n">{counts[ci]}</span>
                </button>
              ))}
            </div>
            <div className="tour-hero-f">
              <span className="xs faint">About {MINUTES} minutes · <kbd>←</kbd> <kbd>→</kbd> to move · <kbd>Esc</kbd> to leave · pick any chapter above</span>
              <span className="spacer" />
              {saved && !saved.finished && saved.idx > 0 && <button className="btn sec" onClick={() => go(Math.min(saved.idx, steps.length - 1))}>Resume at step {saved.idx + 1}</button>}
              <button className="btn tour-next" onClick={() => go(0)}><Icon name="play" className="sm" />Start the tour</button>
            </div>
          </div>
        </div>
      )}

      {phase === "done" && (
        <div className="tour-modal">
          <div className="tour-confetti" aria-hidden>{Array.from({ length: 28 }, (_, i) => <i key={i} style={{ left: `${(i * 37) % 100}%`, background: CHAPTERS[i % CHAPTERS.length].color, animationDelay: `${(i % 7) * 90}ms`, animationDuration: `${1400 + (i % 5) * 220}ms` }} />)}</div>
          <div className="tour-hero done">
            <button className="ibtn tour-x" onClick={onClose} title="Close (Esc)"><Icon name="close" /></button>
            <span className="tour-logo ok" aria-hidden><Icon name="check" /></span>
            <h1>You're all set</h1>
            <p className="tour-lede">That's the whole workbench. Search <b>onboarding</b> any time to come back to a chapter.</p>
            <div className="tour-ticks">{CHAPTERS.map((c) => <span key={c.id} style={{ ["--tc" as string]: c.color }}><Icon name="pass-filled" className="xs" />{c.title}</span>)}</div>
            <div className="tour-next-acts">
              <button onClick={() => { onClose(); nav("/studio"); }}><Icon name="beaker" /><b>Open the Studio</b><span>Tune the HYBRID MODEL on a company</span></button>
              <button onClick={() => { onClose(); nav("/watchlist"); }}><Icon name="eye" /><b>Make a watchlist</b><span>Collect the companies you follow</span></button>
              <button onClick={() => { onClose(); nav("/agents"); }}><Icon name="zap" /><b>Run a quick sweep</b><span>Send the agents through the news</span></button>
              <button onClick={() => { onClose(); openHelp(); }}><Icon name="book" /><b>Browse the glossary</b><span>Every term, in plain words</span></button>
            </div>
            <div className="tour-hero-f">
              <button className="btn ghost" onClick={restart}><Icon name="refresh" className="sm" />Take the tour again</button>
              <span className="spacer" />
              <button className="btn tour-next" onClick={onClose}>Start exploring</button>
            </div>
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}
