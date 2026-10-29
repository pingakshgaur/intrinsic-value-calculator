import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useDismiss } from "../lib/popup";
import { Icon } from "./ui";

export interface ViewerImage { src: string; title: string }

const ZOOMS = [1, 1.5, 2, 3, 4];

/**
 * A full-window image viewer for a set of images: previous / next (buttons,
 * arrow keys, the thumbnail strip), zoom (buttons, + / -, double-click, the
 * mouse wheel) with drag to pan, and open-in-a-new-tab / download. Escape or
 * a click on the dark backdrop closes it.
 */
export function ImageViewer({ images, index, onIndex, onClose }: { images: ViewerImage[]; index: number; onIndex: (i: number) => void; onClose: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const strip = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const refs = useMemo(() => [root], []);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const n = images.length;
  const cur = images[index];
  const go = (d: number) => { if (n > 1) onIndex((index + d + n) % n); };
  const zoomTo = (z: number) => { setZoom(z); if (z === 1) setPan({ x: 0, y: 0 }); };
  const step = (d: number) => { const i = ZOOMS.indexOf(zoom); zoomTo(ZOOMS[Math.max(0, Math.min(ZOOMS.length - 1, (i < 0 ? 0 : i) + d))]); };

  useDismiss(true, onClose, refs);
  useEffect(() => { zoomTo(1); }, [index]);
  useEffect(() => { strip.current?.querySelector<HTMLElement>(`[data-i="${index}"]`)?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" }); }, [index]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); go(1); }
      else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); go(-1); }
      else if (e.key === "Home") { e.preventDefault(); onIndex(0); }
      else if (e.key === "End") { e.preventDefault(); onIndex(n - 1); }
      else if (e.key === "+" || e.key === "=") step(1);
      else if (e.key === "-") step(-1);
      else if (e.key === "0") zoomTo(1);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });
  useEffect(() => { root.current?.focus(); }, []);
  // the wheel zooms once zoomed in (or with Ctrl): a native listener, as React's is passive and cannot stop the page scrolling
  const wheel = useRef(step);
  wheel.current = (d: number) => step(d);
  const zoomed = useRef(zoom);
  zoomed.current = zoom;
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const h = (e: WheelEvent) => { if (e.ctrlKey || e.metaKey || zoomed.current > 1) { e.preventDefault(); wheel.current(e.deltaY < 0 ? 1 : -1); } };
    el.addEventListener("wheel", h, { passive: false });
    return () => el.removeEventListener("wheel", h);
  }, []);
  if (!cur) return null;

  return createPortal(
    <div ref={root} className="iv" role="dialog" aria-modal="true" aria-label={`${cur.title}, image ${index + 1} of ${n}`} tabIndex={-1}>
      <div className="iv-bar">
        <span className="iv-count mono">{index + 1} / {n}</span>
        <b className="iv-title ellipsis">{cur.title}</b>
        <span className="spacer" />
        <div className="iv-tools">
          <button className="ibtn" onClick={() => step(-1)} disabled={zoom === ZOOMS[0]} title="Zoom out (−)"><Icon name="zoom-out" /></button>
          <button className="iv-z mono" onClick={() => zoomTo(1)} title="Fit to the window (0)">{Math.round(zoom * 100)}%</button>
          <button className="ibtn" onClick={() => step(1)} disabled={zoom === ZOOMS[ZOOMS.length - 1]} title="Zoom in (+)"><Icon name="zoom-in" /></button>
          <i className="iv-sep" />
          <a className="ibtn" href={cur.src} target="_blank" rel="noreferrer" title="Open in a new tab"><Icon name="link-external" /></a>
          <a className="ibtn" href={cur.src} download title="Download"><Icon name="desktop-download" /></a>
          <i className="iv-sep" />
          <button className="ibtn" onClick={onClose} title="Close (Esc)"><Icon name="close" /></button>
        </div>
      </div>
      <div ref={stage} className={`iv-stage ${zoom > 1 ? "zoomed" : ""}`}
        onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
        onMouseMove={(e) => { const d = drag.current; if (d) setPan({ x: d.px + e.clientX - d.x, y: d.py + e.clientY - d.y }); }}
        onMouseUp={() => { drag.current = null; }} onMouseLeave={() => { drag.current = null; }}>
        {n > 1 && <button className="iv-nav prev" onClick={() => go(-1)} title="Previous (←)" aria-label="Previous image"><Icon name="chevron-left" /></button>}
        <img key={cur.src} src={cur.src} alt={cur.title} draggable={false}
          style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}
          onDoubleClick={() => zoomTo(zoom > 1 ? 1 : 2)}
          onMouseDown={(e) => { if (zoom > 1) { e.preventDefault(); drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y }; } }} />
        {n > 1 && <button className="iv-nav next" onClick={() => go(1)} title="Next (→)" aria-label="Next image"><Icon name="chevron-right" /></button>}
      </div>
      {n > 1 && (
        <div className="iv-strip" ref={strip} role="listbox" aria-label="Images">
          {images.map((im, i) => (
            <button key={im.src} data-i={i} role="option" aria-selected={i === index} className={i === index ? "on" : ""} onClick={() => onIndex(i)} title={im.title}>
              <img src={im.src} alt="" loading="lazy" />
            </button>
          ))}
        </div>
      )}
      <div className="iv-hint xs">← → to move · + − to zoom · double-click to zoom · drag to pan · Esc to close</div>
    </div>,
    document.body,
  );
}
