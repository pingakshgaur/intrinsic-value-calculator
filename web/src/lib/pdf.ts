// PDF export. Lists become real text tables (selectable, multi-page); charts,
// graphs and panels become images, split across pages. The libraries load on
// the first export, so they cost nothing until then. Other formats: exporters.ts.

export type Cell = string | number | null | undefined;
type Doc = import("jspdf").jsPDF;
export type Orientation = "auto" | "portrait" | "landscape";
export type PageSize = "a4" | "letter";

// the PDF's built-in fonts cover Latin-1 only
export const latin = (s: Cell) =>
  String(s ?? "").replace(/₹/g, "Rs ").replace(/[−–—]/g, "-").replace(/▲/g, "+").replace(/▼/g, "-").replace(/↑/g, "up ")
    .replace(/↓/g, "down ").replace(/↔/g, "<->").replace(/[“”]/g, '"').replace(/[‘’]/g, "'").replace(/…/g, "...")
    .replace(/[^\u0000-ÿ]/g, "");

/** `title-2026-10-27_1430.ext`, in local time; `base` overrides the title part. */
export const fileName = (title: string, ext = "pdf", base?: string) => {
  const d = new Date(), p = (n: number) => String(n).padStart(2, "0");
  const when = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
  const clean = (s: string) => s.replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-").slice(0, 80);
  return base?.trim() ? `${clean(base) || "export"}.${ext}` : `${clean(title) || "export"}-${when}.${ext}`;
};
/** Hand a file to the browser's download. Every export format saves through here. */
export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export const stamp = () => new Date().toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
export const DISCLAIMER = "Estimates from public information; not investment advice.";

function header(doc: Doc, title: string, subtitle?: string) {
  const w = doc.internal.pageSize.getWidth();
  doc.setFillColor(41, 122, 160);
  doc.rect(0, 0, w, 4, "F");
  doc.setFont("helvetica", "bold");
  doc.setFontSize(14);
  doc.setTextColor(32, 32, 32);
  doc.text(latin(title), 28, 30);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8.5);
  doc.setTextColor(110, 110, 110);
  doc.text(latin(`INTVAL Workbench · ${stamp()}${subtitle ? " · " + subtitle : ""}`), 28, 44);
}

function footers(doc: Doc) {
  const n = doc.getNumberOfPages();
  const w = doc.internal.pageSize.getWidth(), h = doc.internal.pageSize.getHeight();
  for (let i = 1; i <= n; i++) {
    doc.setPage(i);
    doc.setFontSize(7.5);
    doc.setTextColor(140, 140, 140);
    doc.text(latin(DISCLAIMER), 28, h - 16);
    doc.text(`${i} / ${n}`, w - 28, h - 16, { align: "right" });
  }
}

export interface PdfTableOpts { subtitle?: string; orientation?: Orientation; fontSize?: number; pageSize?: PageSize; zebra?: boolean; file?: string }

/** A list as a text table. */
export async function exportTable(title: string, head: Cell[], rows: Cell[][], o: PdfTableOpts = {}) {
  const [{ jsPDF }, auto] = await Promise.all([import("jspdf"), import("jspdf-autotable")]);
  const wide = head.length > 6;
  const orientation = o.orientation && o.orientation !== "auto" ? o.orientation : wide ? "landscape" : "portrait";
  const doc = new jsPDF({ orientation, unit: "pt", format: o.pageSize ?? "a4" });
  header(doc, title, o.subtitle ?? `${rows.length} row${rows.length === 1 ? "" : "s"}`);
  auto.default(doc, {
    head: [head.map(latin)],
    body: rows.map((r) => r.map(latin)),
    startY: 56,
    margin: { left: 28, right: 28, bottom: 30 },
    styles: { fontSize: o.fontSize ?? (wide ? 7 : 8), cellPadding: 3, overflow: "linebreak", textColor: [40, 40, 40] },
    headStyles: { fillColor: [41, 122, 160], textColor: 255, fontStyle: "bold" },
    alternateRowStyles: o.zebra === false ? {} : { fillColor: [245, 246, 248] },
  });
  footers(doc);
  saveBlob(doc.output("blob"), o.file ?? fileName(title));
}

export function themeBackground() {
  const s = getComputedStyle(document.documentElement);
  return s.getPropertyValue("--panel").trim() || "#191a1b";
}

export interface PdfImageOpts { subtitle?: string; orientation?: Orientation; pageSize?: PageSize; file?: string }

/** A canvas (a chart image) on as many pages as it needs. */
export async function exportCanvas(canvas: HTMLCanvasElement, title: string, o: PdfImageOpts = {}) {
  const { jsPDF } = await import("jspdf");
  const landscape = o.orientation && o.orientation !== "auto" ? o.orientation === "landscape" : canvas.width > canvas.height * 0.9;
  const doc = new jsPDF({ orientation: landscape ? "landscape" : "portrait", unit: "pt", format: o.pageSize ?? "a4" });
  const pw = doc.internal.pageSize.getWidth(), ph = doc.internal.pageSize.getHeight();
  const top = 56, bottom = 30, side = 28;
  const scale = (pw - side * 2) / canvas.width;
  const slice = Math.floor((ph - top - bottom) / scale);
  for (let y = 0, page = 0; y < canvas.height; y += slice, page++) {
    if (page) doc.addPage();
    header(doc, title, o.subtitle);
    const h = Math.min(slice, canvas.height - y);
    const part = document.createElement("canvas");
    part.width = canvas.width;
    part.height = h;
    part.getContext("2d")!.drawImage(canvas, 0, y, canvas.width, h, 0, 0, canvas.width, h);
    doc.addImage(part.toDataURL("image/jpeg", 0.92), "JPEG", side, top, canvas.width * scale, h * scale);
  }
  footers(doc);
  saveBlob(doc.output("blob"), o.file ?? fileName(title));
}

export interface CaptureOpts { scale?: number; colours?: "screen" | "light"; background?: string }

/** Any element - a panel, a chart, a whole page - as an image, the way it looks (or in light colours, for printing). */
export async function captureElement(el: HTMLElement, o: CaptureOpts = {}) {
  const { toCanvas } = await import("html-to-image");
  const root = document.documentElement;
  const before = root.dataset.theme;
  if (o.colours === "light" && before !== "light") {
    root.dataset.theme = "light";
    // let the light colours (and charts that read them) settle before the snapshot
    // (a timer, not animation frames: those never fire in a background tab, and the export would hang)
    await new Promise((r) => setTimeout(r, 220));
  }
  try {
    const opts = {
      pixelRatio: o.scale ?? 2, backgroundColor: o.background ?? themeBackground(), cacheBust: true,
      filter: (n: HTMLElement) => !(n instanceof HTMLElement && n.dataset && "noexport" in n.dataset),
      // scrolling areas are exported whole, not just the visible part
      width: el.scrollWidth, height: el.scrollHeight, style: { overflow: "visible", maxHeight: "none", height: `${el.scrollHeight}px` },
    };
    try {
      return await toCanvas(el, opts);
    } catch {
      return await toCanvas(el, { ...opts, skipFonts: true });
    }
  } finally {
    if (o.colours === "light" && before !== "light") {
      if (before) root.dataset.theme = before;
      else delete root.dataset.theme;
    }
  }
}

/** Kept for callers that want the one-click PDF of an element. */
export async function exportElement(el: HTMLElement, title: string, subtitle?: string) {
  await exportCanvas(await captureElement(el), title, { subtitle });
}
