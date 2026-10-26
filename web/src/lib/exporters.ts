// Every export format the app offers. What can be exported decides which formats
// make sense: a table (rows and columns), a chart or panel (an image), or a
// whole page. The libraries load on first use.
import { captureElement, Cell, DISCLAIMER, exportCanvas, exportTable, fileName, latin, Orientation, PageSize, saveBlob, stamp } from "./pdf";

export type ExportKind = "table" | "chart" | "page";
export type Fmt = "xlsx" | "csv" | "docx" | "md" | "pdf" | "png";

export const FORMATS: Record<ExportKind, Fmt[]> = {
  table: ["xlsx", "csv", "docx", "md", "pdf"],
  chart: ["png", "pdf", "docx"],
  page: ["pdf", "docx"],
};
export const FMT_META: Record<Fmt, { label: string; icon: string; hint: string }> = {
  xlsx: { label: "Excel workbook", icon: "table", hint: ".xlsx · sortable, filterable sheet" },
  csv: { label: "CSV", icon: "file-code", hint: ".csv · plain values for any tool" },
  docx: { label: "Word document", icon: "file-text", hint: ".docx · editable report" },
  md: { label: "Markdown", icon: "markdown", hint: ".md · table for notes and wikis" },
  pdf: { label: "PDF", icon: "file-pdf", hint: ".pdf · fixed layout to share or print" },
  png: { label: "PNG image", icon: "file-media", hint: ".png · picture for slides and chats" },
};

const text = (c: Cell) => (c == null ? "" : String(c));
/** "1,234.5" -> 1234.5 for spreadsheets; anything with letters, %, ₹ stays text */
const asNumber = (c: Cell) => {
  if (typeof c === "number") return Number.isFinite(c) ? c : null;
  const s = text(c).trim();
  return /^-?[\d,]*\.?\d+$/.test(s) ? Number(s.replace(/,/g, "")) : null;
};

// ------------------------------------------------------------------ tables
export interface TableExport {
  title: string; subtitle?: string; head: Cell[]; rows: Cell[][]; file?: string;
  orientation?: Orientation; pageSize?: PageSize; fontSize?: number; zebra?: boolean;
  sheet?: string; freeze?: boolean; filter?: boolean; delimiter?: "," | ";" | "\t";
}

export async function exportTableAs(fmt: Fmt, t: TableExport) {
  const name = (ext: string) => fileName(t.title, ext, t.file);
  if (fmt === "pdf") return exportTable(t.title, t.head, t.rows, { subtitle: t.subtitle, orientation: t.orientation, pageSize: t.pageSize, fontSize: t.fontSize, zebra: t.zebra, file: name("pdf") });
  if (fmt === "csv") {
    const d = t.delimiter ?? ",";
    const q = (c: Cell) => { const s = text(c); return /["\n\r]/.test(s) || s.includes(d) ? `"${s.replace(/"/g, '""')}"` : s; };
    const body = [t.head, ...t.rows].map((r) => r.map(q).join(d)).join("\r\n");
    return saveBlob(new Blob(["﻿" + body], { type: "text/csv;charset=utf-8" }), name("csv")); // BOM: Excel reads ₹ correctly
  }
  if (fmt === "md") {
    const esc = (c: Cell) => text(c).replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
    const right = t.rows.length ? t.head.map((_, i) => t.rows.every((r) => r[i] == null || r[i] === "" || asNumber(r[i]) != null)) : t.head.map(() => false);
    const md = [`# ${t.title}`, "", `${t.subtitle ? t.subtitle + " · " : ""}INTVAL Workbench · ${stamp()}`, "",
      `| ${t.head.map(esc).join(" | ")} |`, `| ${right.map((r) => (r ? "---:" : "---")).join(" | ")} |`,
      ...t.rows.map((r) => `| ${t.head.map((_, i) => esc(r[i])).join(" | ")} |`), "", `_${DISCLAIMER}_`, ""].join("\n");
    return saveBlob(new Blob([md], { type: "text/markdown;charset=utf-8" }), name("md"));
  }
  if (fmt === "xlsx") {
    const ExcelJS = (await import("exceljs")).default;
    const wb = new ExcelJS.Workbook();
    wb.creator = "INTVAL Workbench";
    const ws = wb.addWorksheet((t.sheet || t.title).replace(/[\\/?*[\]:]/g, " ").slice(0, 31) || "Sheet1", {
      views: t.freeze === false ? [] : [{ state: "frozen", ySplit: 1 }],
    });
    ws.addRow(t.head.map(text));
    for (const r of t.rows) ws.addRow(t.head.map((_, i) => asNumber(r[i]) ?? text(r[i])));
    const top = ws.getRow(1);
    top.font = { bold: true, color: { argb: "FFFFFFFF" } };
    top.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF297AA0" } };
    ws.columns.forEach((col, i) => {
      const longest = Math.max(text(t.head[i]).length, ...t.rows.slice(0, 500).map((r) => text(r[i]).length));
      col.width = Math.min(60, Math.max(8, longest + 2));
    });
    if (t.filter !== false && t.rows.length) ws.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: t.head.length } };
    const buf = await wb.xlsx.writeBuffer();
    return saveBlob(new Blob([buf], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), name("xlsx"));
  }
  if (fmt === "docx") {
    const D = await import("docx");
    const landscape = t.orientation === "landscape" || (t.orientation !== "portrait" && t.head.length > 6);
    const size = t.fontSize ? t.fontSize * 2 : landscape ? 15 : 17; // half-points
    const cell = (c: Cell, head = false, shade = false) => new D.TableCell({
      children: [new D.Paragraph({ children: [new D.TextRun({ text: text(c), bold: head, color: head ? "FFFFFF" : "202020", size })] })],
      shading: head ? { fill: "297AA0", type: D.ShadingType.CLEAR, color: "auto" } : shade ? { fill: "F5F6F8", type: D.ShadingType.CLEAR, color: "auto" } : undefined,
      margins: { top: 40, bottom: 40, left: 70, right: 70 },
    });
    const table = new D.Table({
      width: { size: 100, type: D.WidthType.PERCENTAGE },
      rows: [
        new D.TableRow({ tableHeader: true, children: t.head.map((h) => cell(h, true)) }),
        ...t.rows.map((r, j) => new D.TableRow({ children: t.head.map((_, i) => cell(r[i], false, t.zebra !== false && j % 2 === 1)) })),
      ],
    });
    const doc = docShell(D, t.title, t.subtitle ?? `${t.rows.length} rows`, landscape, t.pageSize, [table]);
    return saveBlob(await D.Packer.toBlob(doc), name("docx"));
  }
  throw new Error(`a table cannot be saved as ${fmt}`);
}

type DocxLib = typeof import("docx");
function docShell(D: DocxLib, title: string, subtitle: string | undefined, landscape: boolean, pageSize: PageSize | undefined, body: (import("docx").Paragraph | import("docx").Table)[]) {
  const [w, h] = pageSize === "letter" ? [12240, 15840] : [11906, 16838]; // twips
  return new D.Document({
    creator: "INTVAL Workbench",
    title,
    sections: [{
      properties: { page: { size: { width: landscape ? h : w, height: landscape ? w : h, orientation: landscape ? D.PageOrientation.LANDSCAPE : D.PageOrientation.PORTRAIT }, margin: { top: 720, bottom: 720, left: 720, right: 720 } } },
      footers: { default: new D.Footer({ children: [new D.Paragraph({ children: [new D.TextRun({ text: DISCLAIMER, size: 15, color: "8C8C8C" })] })] }) },
      children: [
        new D.Paragraph({ heading: D.HeadingLevel.HEADING_1, children: [new D.TextRun({ text: title })] }),
        new D.Paragraph({ spacing: { after: 200 }, children: [new D.TextRun({ text: `INTVAL Workbench · ${stamp()}${subtitle ? " · " + subtitle : ""}`, size: 18, color: "6E6E6E" })] }),
        ...body,
      ],
    }],
  });
}

// ------------------------------------------------------------------ images
export interface ImageExport {
  title: string; subtitle?: string; file?: string; orientation?: Orientation; pageSize?: PageSize;
  /** PNG: draw the title and date in a band above the picture */
  band?: boolean; padding?: number;
}

/** The captured picture with padding (and, for PNG, a title band) around it. */
export function frame(canvas: HTMLCanvasElement, o: { padding?: number; band?: boolean; title?: string; subtitle?: string; scale?: number; background: string; ink: string; quiet: string }) {
  const s = o.scale ?? 2, pad = Math.round((o.padding ?? 0) * s), band = o.band ? Math.round(52 * s) : 0;
  const out = document.createElement("canvas");
  out.width = canvas.width + pad * 2;
  out.height = canvas.height + pad * 2 + band;
  const g = out.getContext("2d")!;
  g.fillStyle = o.background;
  g.fillRect(0, 0, out.width, out.height);
  if (band) {
    g.fillStyle = o.ink;
    g.font = `600 ${Math.round(17 * s)}px Inter, system-ui, sans-serif`;
    g.fillText(o.title ?? "", pad + 4 * s, pad + 24 * s);
    g.fillStyle = o.quiet;
    g.font = `${Math.round(11.5 * s)}px Inter, system-ui, sans-serif`;
    g.fillText(`INTVAL Workbench · ${stamp()}${o.subtitle ? " · " + o.subtitle : ""}`, pad + 4 * s, pad + 42 * s);
  }
  g.drawImage(canvas, pad, pad + band);
  return out;
}

const toBlob = (c: HTMLCanvasElement) => new Promise<Blob>((ok, bad) => c.toBlob((b) => (b ? ok(b) : bad(new Error("the picture could not be encoded"))), "image/png"));

export async function exportImageAs(fmt: Fmt, canvas: HTMLCanvasElement, o: ImageExport) {
  const name = (ext: string) => fileName(o.title, ext, o.file);
  if (fmt === "png") return saveBlob(await toBlob(canvas), name("png"));
  if (fmt === "pdf") return exportCanvas(canvas, latin(o.title), { subtitle: o.subtitle, orientation: o.orientation, pageSize: o.pageSize, file: name("pdf") });
  if (fmt === "docx") {
    const D = await import("docx");
    const landscape = o.orientation === "landscape" || (o.orientation !== "portrait" && canvas.width > canvas.height * 0.9);
    const [pw, ph] = o.pageSize === "letter" ? [8.5, 11] : [8.27, 11.69];
    // usable area in pixels at 96 dpi, inside half-inch margins and under the title
    const usableW = ((landscape ? ph : pw) - 1) * 96, usableH = ((landscape ? pw : ph) - 1) * 96 - 110;
    const k = usableW / canvas.width;
    const slice = Math.max(1, Math.floor(usableH / k));
    const parts: import("docx").Paragraph[] = [];
    for (let y = 0; y < canvas.height; y += slice) {
      const h = Math.min(slice, canvas.height - y);
      const part = document.createElement("canvas");
      part.width = canvas.width;
      part.height = h;
      part.getContext("2d")!.drawImage(canvas, 0, y, canvas.width, h, 0, 0, canvas.width, h);
      const data = new Uint8Array(await (await toBlob(part)).arrayBuffer());
      parts.push(new D.Paragraph({ pageBreakBefore: y > 0, children: [new D.ImageRun({ type: "png", data, transformation: { width: Math.round(canvas.width * k), height: Math.round(h * k) } })] }));
    }
    const doc = docShell(D, o.title, o.subtitle, landscape, o.pageSize, parts);
    return saveBlob(await D.Packer.toBlob(doc), name("docx"));
  }
  throw new Error(`a picture cannot be saved as ${fmt}`);
}

export { captureElement, saveBlob };
