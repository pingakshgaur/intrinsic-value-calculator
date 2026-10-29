// Shared behaviour for every popup (menus, dropdowns, popovers): where it
// sits, and when it closes.
import { CSSProperties, RefObject, useEffect, useLayoutEffect, useState } from "react";

/**
 * Place a popup under (or, without room, over) its trigger, on the page's top
 * layer: fixed to the window, so a scrolling table or a clipped panel never
 * cuts it off, and kept inside the window's edges.
 */
export function usePlacement(open: boolean, trigger: RefObject<HTMLElement | null>, pop: RefObject<HTMLElement | null>, align: "start" | "end" = "end", gap = 6) {
  const [style, setStyle] = useState<CSSProperties>({ position: "fixed", visibility: "hidden" });
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const t = trigger.current?.getBoundingClientRect(), el = pop.current;
      if (!t || !el) return;
      const w = el.offsetWidth, h = el.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
      // the stylesheet's own height limit, read once before an inline one is set
      if (!el.dataset.max) el.dataset.max = String(parseFloat(getComputedStyle(el).maxHeight) || 0);
      const cssMax = Number(el.dataset.max);
      let left = align === "end" ? t.right - w : t.left;
      left = Math.max(8, Math.min(left, vw - w - 8));
      const below = vh - t.bottom - gap - 8, above = t.top - gap - 8;
      const up = h > below && above > below;
      const top = up ? Math.max(8, t.top - gap - h) : t.bottom + gap;
      setStyle({ position: "fixed", left, top, right: "auto", bottom: "auto", maxHeight: Math.max(160, Math.min(cssMax || Infinity, up ? above : below)), visibility: "visible" });
    };
    place();
    const ro = new ResizeObserver(place);
    if (pop.current) ro.observe(pop.current);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { ro.disconnect(); window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open, trigger, pop, align, gap]);
  return style;
}

// every open popup, oldest first: a dropdown opened inside a popover sits above
// it, so a click in the dropdown's list does not close the popover, and Escape
// closes only the topmost one
const open_: RefObject<HTMLElement | null>[][] = [];

/** True while any popup is open (a drawer leaves Escape to it). */
export const popupOpen = () => open_.length > 0;

/** Close on a click outside the trigger and the popup (and any popup opened from it), and on Escape when it is the top one. */
export function useDismiss(open: boolean, close: () => void, refs: RefObject<HTMLElement | null>[]) {
  useEffect(() => {
    if (!open) return;
    open_.push(refs);
    const h = (e: MouseEvent) => {
      const i = open_.indexOf(refs);
      const t = e.target as Node;
      if (!open_.slice(i).some((rs) => rs.some((r) => r.current?.contains(t)))) close();
    };
    const k = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || open_[open_.length - 1] !== refs) return;
      e.stopPropagation();
      close();
    };
    document.addEventListener("mousedown", h);
    window.addEventListener("keydown", k, true);
    return () => {
      document.removeEventListener("mousedown", h);
      window.removeEventListener("keydown", k, true);
      const i = open_.indexOf(refs);
      if (i >= 0) open_.splice(i, 1);
    };
  }, [open, close, refs]);
}
