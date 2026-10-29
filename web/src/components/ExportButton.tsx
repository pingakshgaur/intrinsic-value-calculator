import { RefObject, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Cell, Orientation, PageSize, themeBackground } from "../lib/pdf";
import { captureElement, ExportKind, exportImageAs, exportTableAs, Fmt, FMT_META, FORMATS, frame } from "../lib/exporters";
import { Icon, Popover, Toggle } from "./ui";
import { useApp } from "./workbenchContext";

/** The download mark: an arrow into a tray, drawn to match the codicons' weight. */
function DownloadGlyph() {
  return (
    <svg className="dl-glyph" width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8 2.2v8" /><path d="M4.6 7.2 8 10.6l3.4-3.4" /><path d="M2.6 10.4v2.1c0 .7.5 1.2 1.2 1.2h8.4c.7 0 1.2-.5 1.2-1.2v-2.1" />
    </svg>
  );
}

export interface TableData { head: Cell[]; rows: Cell[][]; subtitle?: string }

/**
 * Export ▾ - the formats that suit what is being exported, each opening a small
 * editor (name, title, columns, page, colours...) with a preview before the file
 * is saved. Give it `table` (rows), `target` (an element: a chart, a panel, or a
 * whole page with kind="page"), or `canvas` (a picture drawn on demand).
 * `data` adds the page's data as a first section of the same menu, so a page
 * has one download button, not one for its rows and another for the page.
 */
export function ExportButton({ title, table, target, canvas, kind, label, className = "ibtn", tip, data }: {
  title: string;
  table?: () => TableData;
  target?: RefObject<HTMLElement | null> | (() => HTMLElement | null);
  canvas?: () => Promise<HTMLCanvasElement | null>;
  kind?: ExportKind;
  label?: string;
  className?: string;
  tip?: string;
  data?: () => TableData;
}) {
  const what: ExportKind = kind ?? (table ? "table" : "chart");
  const [open, setOpen] = useState<{ fmt: Fmt; kind: ExportKind } | null>(null);
  const groups: { kind: ExportKind; head: string }[] = [
    ...(data ? [{ kind: "table" as ExportKind, head: "Download the data as" }] : []),
    { kind: what, head: `Download ${what === "table" ? "the data" : what === "page" ? "the whole page" : "this view"} as` },
  ];
  const formats = groups.flatMap((g) => FORMATS[g.kind]);
  return (
    <>
      <Popover className="menu export-menu" trigger={(on, toggle) => (
        // one look everywhere: a download icon; the formats are in the menu
        <button className={`${className} dl ${on ? "on" : ""}`} data-noexport onClick={toggle} aria-haspopup="menu" aria-expanded={on}
          aria-label={label ? `${label}: ${title}` : `Download ${title}`}
          title={tip ?? `Download “${title}” (${[...new Set(formats)].map((f) => f.toUpperCase()).join(", ")})`}>
          <DownloadGlyph />
        </button>
      )}>
        {(close) => (
          <div data-noexport>
            {groups.map((g, gi) => (
              <div key={gi}>
                {gi > 0 && <hr />}
                <div className="label export-h">{g.head}</div>
                {FORMATS[g.kind].map((f) => (
                  <button key={f} className="export-item" onClick={() => { close(); setOpen({ fmt: f, kind: g.kind }); }}>
                    <span className="ic"><Icon name={FMT_META[f].icon} className="sm" /></span>
                    <span className="tx"><b>{FMT_META[f].label}</b><small>{FMT_META[f].hint}</small></span>
                    <span className="ext">{f.toUpperCase()}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}
      </Popover>
      {open && createPortal(<ExportDialog fmt={open.fmt} kind={open.kind} title={title} table={open.kind === "table" && data ? data : table} target={target} canvas={canvas}
        onClose={() => setOpen(null)} onFormat={(f) => setOpen({ fmt: f, kind: open.kind })} />, document.body)}
    </>
  );
}

const SIZE_PRESET = [{ v: 7, l: "Small" }, { v: 8.5, l: "Normal" }, { v: 10, l: "Large" }];

function ExportDialog({ fmt, kind, title, table, target, canvas, onClose, onFormat }: {
  fmt: Fmt; kind: ExportKind; title: string; table?: () => TableData;
  target?: RefObject<HTMLElement | null> | (() => HTMLElement | null); canvas?: () => Promise<HTMLCanvasElement | null>;
  onClose: () => void; onFormat: (f: Fmt) => void;
}) {
  const app = useApp();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // shared
  const [docTitle, setDocTitle] = useState(title);
  const [file, setFile] = useState("");
  const [subtitle, setSubtitle] = useState("");
  // tables: a snapshot taken when the editor opens, so live data does not shift under you
  const data = useMemo(() => (table ? table() : null), []); // eslint-disable-line react-hooks/exhaustive-deps
  const [cols, setCols] = useState<boolean[]>(() => (data ? data.head.map(() => true) : []));
  const [limit, setLimit] = useState<number | "">("");
  const [orientation, setOrientation] = useState<Orientation>("auto");
  const [pageSize, setPageSize] = useState<PageSize>("a4");
  const [fontSize, setFontSize] = useState(8.5);
  const [zebra, setZebra] = useState(true);
  const [sheet, setSheet] = useState("");
  const [freeze, setFreeze] = useState(true);
  const [filter, setFilter] = useState(true);
  const [delimiter, setDelimiter] = useState<"," | ";" | "\t">(",");
  // pictures
  const [colours, setColours] = useState<"screen" | "light">("screen");
  const [scale, setScale] = useState(2);
  const [padding, setPadding] = useState(16);
  const [band, setBand] = useState(true);
  const [shot, setShot] = useState<HTMLCanvasElement | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const isTable = kind === "table";
  const ext = fmt;

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  // take the picture (again when colours or sharpness change)
  const shotKey = `${colours}|${scale}`;
  useEffect(() => {
    if (isTable) return;
    let stop = false;
    setShot(null);
    setErr(null);
    (async () => {
      try {
        const c = canvas ? await canvas() : await (async () => {
          const el = typeof target === "function" ? target() : target?.current;
          return el ? captureElement(el, { scale, colours }) : null;
        })();
        if (!stop) { if (c) setShot(c); else setErr("Nothing to export here yet."); }
      } catch (e) { if (!stop) setErr(e instanceof Error ? e.message : String(e)); }
    })();
    return () => { stop = true; };
  }, [shotKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const light = colours === "light";
  const framed = useMemo(() => {
    if (!shot) return null;
    const css = getComputedStyle(document.documentElement);
    return frame(shot, {
      padding, band: fmt === "png" && band, title: docTitle, subtitle, scale: canvas ? 1 : scale,
      background: light ? "#ffffff" : themeBackground(),
      ink: light ? "#1f2328" : css.getPropertyValue("--fg-1").trim() || "#e6e6e6",
      quiet: light ? "#6e7781" : css.getPropertyValue("--fg-3").trim() || "#8c8c8c",
    });
  }, [shot, padding, band, docTitle, subtitle, fmt, light, scale, canvas]);
  useEffect(() => {
    if (!framed) { setPreview(null); return; }
    // a small preview: the full-size picture can be many megapixels
    const k = Math.min(1, 900 / framed.width);
    const p = document.createElement("canvas");
    p.width = Math.max(1, Math.round(framed.width * k));
    p.height = Math.max(1, Math.round(framed.height * k));
    p.getContext("2d")!.drawImage(framed, 0, 0, p.width, p.height);
    setPreview(p.toDataURL("image/png"));
  }, [framed]);

  const pickedHead = data ? data.head.filter((_, i) => cols[i]) : [];
  const pickedRows = data ? data.rows.slice(0, limit === "" ? undefined : Math.max(1, limit)).map((r) => r.filter((_, i) => cols[i])) : [];

  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      if (isTable) {
        if (!pickedHead.length) throw new Error("pick at least one column");
        if (!pickedRows.length) throw new Error("there are no rows to export");
        await exportTableAs(fmt, { title: docTitle || title, subtitle: subtitle || data?.subtitle, head: pickedHead, rows: pickedRows, file,
          orientation, pageSize, fontSize, zebra, sheet, freeze, filter, delimiter });
      } else {
        if (!framed) throw new Error("the picture is not ready yet");
        await exportImageAs(fmt, framed, { title: docTitle || title, subtitle, file, orientation, pageSize });
      }
      app.toast(`Saved “${docTitle || title}” as ${fmt.toUpperCase()}`, "ok");
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const seg = <T extends string | number>(value: T, set: (v: T) => void, opts: { v: T; l: string }[]) => (
    <div className="seg">{opts.map((o) => <button key={String(o.v)} className={value === o.v ? "on" : ""} onClick={() => set(o.v)}>{o.l}</button>)}</div>
  );
  const paged = fmt === "pdf" || fmt === "docx";

  return (
    <>
      <div className="scrim" onMouseDown={onClose} data-noexport />
      <div className="xd" role="dialog" aria-label={`Export ${title}`} data-noexport>
        <header className="xd-h">
          <Icon name={FMT_META[fmt].icon} />
          <div className="grow"><b>Download as {FMT_META[fmt].label}</b><small>{title}</small></div>
          <button className="ibtn" onClick={onClose} title="Close (Esc)"><Icon name="close" /></button>
        </header>
        <div className="xd-b">
          <div className="xd-form">
            <div className="xd-sec">
              <label className="fld"><span>Title</span><input className="inp sm" value={docTitle} onChange={(e) => setDocTitle(e.target.value)} /></label>
              {fmt !== "csv" && <label className="fld"><span>Note under the title</span><input className="inp sm" value={subtitle} placeholder={data?.subtitle ?? "optional"} onChange={(e) => setSubtitle(e.target.value)} /></label>}
              <label className="fld"><span>File name</span>
                <div className="xd-file"><input className="inp sm" value={file} placeholder={docTitle.replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-") + "-<date>"} onChange={(e) => setFile(e.target.value)} /><span className="mono xs faint">.{ext}</span></div>
              </label>
            </div>
            {isTable && data && (
              <div className="xd-sec">
                <div className="xd-lab">Columns <span className="faint">{pickedHead.length}/{data.head.length}</span>
                  <button className="btn xs ghost" onClick={() => setCols(data.head.map(() => true))}>All</button>
                  <button className="btn xs ghost" onClick={() => setCols(data.head.map((_, i) => i === 0))}>First only</button></div>
                <div className="xd-cols">{data.head.map((h, i) => (
                  <label key={i} className={cols[i] ? "on" : ""}><input type="checkbox" className="cb" checked={cols[i]} onChange={() => setCols(cols.map((c, j) => (j === i ? !c : c)))} />{String(h ?? `Column ${i + 1}`)}</label>
                ))}</div>
                <label className="fld"><span>Rows</span>
                  <div className="row" style={{ gap: 8 }}><input className="inp sm num" type="number" min={1} max={data.rows.length} value={limit} placeholder={`all ${data.rows.length}`} style={{ width: 110 }}
                    onChange={(e) => setLimit(e.target.value === "" ? "" : Math.max(1, Math.min(data.rows.length, Number(e.target.value))))} /><span className="xs faint">{limit === "" ? "every row" : `first ${limit} of ${data.rows.length}`}</span></div>
                </label>
              </div>
            )}
            <div className="xd-sec">
              {fmt === "xlsx" && <>
                <label className="fld"><span>Sheet name</span><input className="inp sm" maxLength={31} value={sheet} placeholder={docTitle.slice(0, 31)} onChange={(e) => setSheet(e.target.value)} /></label>
                <Toggle checked={freeze} onChange={setFreeze} label="Keep the header row in view" />
                <Toggle checked={filter} onChange={setFilter} label="Add filter buttons to the header" />
              </>}
              {fmt === "csv" && <div className="fld"><span>Separator</span>{seg(delimiter, setDelimiter, [{ v: ",", l: "Comma" }, { v: ";", l: "Semicolon" }, { v: "\t", l: "Tab" }])}</div>}
              {paged && <>
                <div className="fld"><span>Page</span>{seg(pageSize, setPageSize, [{ v: "a4", l: "A4" }, { v: "letter", l: "Letter" }])}</div>
                <div className="fld"><span>Orientation</span>{seg(orientation, setOrientation, [{ v: "auto", l: "Auto" }, { v: "portrait", l: "Portrait" }, { v: "landscape", l: "Landscape" }])}</div>
              </>}
              {isTable && paged && <>
                <div className="fld"><span>Text size</span>{seg(fontSize, setFontSize, SIZE_PRESET)}</div>
                <Toggle checked={zebra} onChange={setZebra} label="Shade every other row" />
              </>}
              {!isTable && <>
                {!canvas && <div className="fld"><span>Colours</span>{seg(colours, setColours, [{ v: "screen", l: "As on screen" }, { v: "light", l: "Light, for printing" }])}</div>}
                {!canvas && <div className="fld"><span>Sharpness</span>{seg(scale, setScale, [{ v: 1, l: "Standard" }, { v: 2, l: "Sharp" }, { v: 3, l: "Extra sharp" }])}</div>}
                <label className="fld"><span>Margin around it · {padding}px</span><input type="range" className="sl" min={0} max={48} step={4} value={padding} onChange={(e) => setPadding(Number(e.target.value))} /></label>
                {fmt === "png" && <Toggle checked={band} onChange={setBand} label="Title and date above the picture" />}
              </>}
            </div>
            <div className="xd-sec">
              <div className="xd-lab">Other formats</div>
              <div className="xd-fmts">{FORMATS[kind].map((f) => <button key={f} className={`chip ${f === fmt ? "on" : ""}`} onClick={() => onFormat(f)}>{f.toUpperCase()}</button>)}</div>
            </div>
          </div>
          <div className="xd-prev">
            <div className="xd-lab">Preview</div>
            {isTable ? (
              <div className="xd-table">
                <table className="dg dense"><thead><tr>{pickedHead.map((h, i) => <th key={i}>{String(h ?? "")}</th>)}</tr></thead>
                  <tbody>{pickedRows.slice(0, 12).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{String(c ?? "")}</td>)}</tr>)}</tbody></table>
                {pickedRows.length > 12 && <div className="xs faint" style={{ padding: 8 }}>…and {pickedRows.length - 12} more rows</div>}
                {!pickedHead.length && <div className="xs faint" style={{ padding: 12 }}>No columns picked.</div>}
              </div>
            ) : (
              <div className={`xd-img ${light ? "light" : ""}`}>
                {preview ? <img src={preview} alt={`Preview of ${title}`} /> : err ? null : <span className="xs faint"><Icon name="loading" className="spin xs" /> Taking the picture…</span>}
              </div>
            )}
            {err && <div className="note err" style={{ marginTop: 10 }}><Icon name="error" /><div>{err}</div></div>}
          </div>
        </div>
        <footer className="xd-f">
          <span className="xs faint">{isTable ? `${pickedRows.length} rows × ${pickedHead.length} columns` : framed ? `${framed.width} × ${framed.height} px` : ""}</span>
          <span className="spacer" />
          <button className="btn sec" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={busy || (!isTable && !framed)} onClick={go}><Icon name={busy ? "loading" : "desktop-download"} className={`sm ${busy ? "spin" : ""}`} />Download {fmt.toUpperCase()}</button>
        </footer>
      </div>
    </>
  );
}

