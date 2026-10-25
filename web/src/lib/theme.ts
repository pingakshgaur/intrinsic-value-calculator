// Light / dark theme. The choice lives on <html data-theme>, set before the
// first paint by index.html, so CSS does the work; canvas charts read the
// resolved colours through themeColors() and redraw on "themechange".
import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

export type Theme = "dark" | "light";
const KEY = "intval.theme";

export const getTheme = (): Theme => (document.documentElement.dataset.theme === "light" ? "light" : "dark");

function apply(t: Theme) {
  document.documentElement.dataset.theme = t;
  document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", t);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", t === "light" ? "#FAFAFD" : "#191A1B");
  try { localStorage.setItem(KEY, t); } catch { /* private mode */ }
  window.dispatchEvent(new CustomEvent("themechange", { detail: t }));
}

/** Switch theme; with `from` (the button), the new theme grows as a circle from it. */
export function setTheme(t: Theme, from?: HTMLElement | null, onApplied?: () => void) {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } };
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const run = () => flushSync(() => { apply(t); onApplied?.(); });
  if (!doc.startViewTransition || !from || reduce) return run();
  const r = from.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const end = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
  const vt = doc.startViewTransition(run);
  vt.ready.then(() => {
    document.documentElement.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${end}px at ${x}px ${y}px)`] },
      { duration: 550, easing: "cubic-bezier(.4,0,.2,1)", pseudoElement: "::view-transition-new(root)" },
    );
  }).catch(() => { /* transition skipped */ });
}

export function useTheme(): Theme {
  const [t, setT] = useState<Theme>(getTheme);
  useEffect(() => {
    const on = () => setT(getTheme());
    window.addEventListener("themechange", on);
    return () => window.removeEventListener("themechange", on);
  }, []);
  return t;
}

/** Resolved token colours for canvas drawing (Lightweight Charts). */
export function themeColors() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    theme: getTheme(), bg: v("--bg"), panel: v("--panel"), line: v("--line"), line2: v("--line-2"),
    fg: v("--fg"), fg1: v("--fg-1"), fg2: v("--fg-2"), fg3: v("--fg-3"), up: v("--up"), down: v("--down"),
    blue: v("--c-blue"), yellow: v("--c-yellow"), orange: v("--c-orange"), purple: v("--c-purple"),
    hm: v("--hm"), price: v("--price"), grid: v("--c-grid"), accent: v("--accent"),
  };
}
export type ThemeColors = ReturnType<typeof themeColors>;
