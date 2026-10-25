// One-click PDF export. Lists become real text tables (selectable, multi-page);
// charts, graphs and panels become images, split across A4 pages. The
// libraries load on the first export, so they cost nothing until then.

export type Cell = string | number | null | undefined;
type Doc = import("jspdf").jsPDF;

// the PDF's built-in fonts cover Latin-1 only
export const latin = (s: Cell) =>
  String(s ?? "").replace(/₹/g, "Rs ").replace(/[−–—]/g, "-").replace(/▲/g, "+").replace(/▼/g, "-").replace(/↑/g, "up ")
    .replace(/↓/g, "down ").replace(/↔/g, "<->").replace(/[“”]/g, '"').replace(/[‘’]/g, "'").replace(/…/g, "...")
    .replace(/[^\u0000-ÿ]/g, "");

const fileName = (title: string) => {
  const d = new Date(), p = (n: number) => String(n).padStart(2, "0");
  const when = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;  // local time
  return `${title.replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-").slice(0, 60) || "export"}-${when}.pdf`;
};
const stamp = () => new Date().toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });

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
    doc.text(latin("Estimates from public information; not investment advice."), 28, h - 16);
    doc.text(`${i} / ${n}`, w - 28, h - 16, { align: "right" });
  }
}

/** A list as a text table. */
export async function exportTable(title: string, head: Cell[], rows: Cell[][], subtitle?: string) {
  const [{ jsPDF }, auto] = await Promise.all([import("jspdf"), import("jspdf-autotable")]);
  const wide = head.length > 6;
  const doc = new jsPDF({ orientation: wide ? "landscape" : "portrait", unit: "pt", format: "a4" });
  header(doc, title, subtitle ?? `${rows.length} row${rows.length === 1 ? "" : "s"}`);
  auto.default(doc, {
    head: [head.map(latin)],
    body: rows.map((r) => r.map(latin)),
    startY: 56,
    margin: { left: 28, right: 28, bottom: 30 },
    styles: { fontSize: wide ? 7 : 8, cellPadding: 3, overflow: "linebreak", textColor: [40, 40, 40] },
    headStyles: { fillColor: [41, 122, 160], textColor: 255, fontStyle: "bold" },
    alternateRowStyles: { fillColor: [245, 246, 248] },
  });
  footers(doc);
  doc.save(fileName(title));
}

function bg() {
  const s = getComputedStyle(document.documentElement);
  return s.getPropertyValue("--panel").trim() || "#191a1b";
}

/** A canvas (a chart image) on as many pages as it needs. */
export async function exportCanvas(canvas: HTMLCanvasElement, title: string, subtitle?: string) {
  const { jsPDF } = await import("jspdf");
  const landscape = canvas.width > canvas.height * 0.9;
  const doc = new jsPDF({ orientation: landscape ? "landscape" : "portrait", unit: "pt", format: "a4" });
  const pw = doc.internal.pageSize.getWidth(), ph = doc.internal.pageSize.getHeight();
  const top = 56, bottom = 30, side = 28;
  const scale = (pw - side * 2) / canvas.width;
  const slice = Math.floor((ph - top - bottom) / scale);
  for (let y = 0, page = 0; y < canvas.height; y += slice, page++) {
    if (page) doc.addPage();
    header(doc, title, subtitle);
    const h = Math.min(slice, canvas.height - y);
    const part = document.createElement("canvas");
    part.width = canvas.width;
    part.height = h;
    part.getContext("2d")!.drawImage(canvas, 0, y, canvas.width, h, 0, 0, canvas.width, h);
    doc.addImage(part.toDataURL("image/jpeg", 0.92), "JPEG", side, top, canvas.width * scale, h * scale);
  }
  footers(doc);
  doc.save(fileName(title));
}

/** Any element - a panel, a chart, a graph, a whole page - as it looks on screen. */
export async function exportElement(el: HTMLElement, title: string, subtitle?: string) {
  const { toCanvas } = await import("html-to-image");
  const opts = {
    pixelRatio: 2, backgroundColor: bg(), cacheBust: true,
    filter: (n: HTMLElement) => !(n instanceof HTMLElement && n.dataset && "noexport" in n.dataset),
    // scrolling areas are exported whole, not just the visible part
    width: el.scrollWidth, height: el.scrollHeight, style: { overflow: "visible", maxHeight: "none", height: `${el.scrollHeight}px` },
  };
  let canvas: HTMLCanvasElement;
  try {
    canvas = await toCanvas(el, opts);
  } catch {
    canvas = await toCanvas(el, { ...opts, skipFonts: true });
  }
  await exportCanvas(canvas, title, subtitle);
}
