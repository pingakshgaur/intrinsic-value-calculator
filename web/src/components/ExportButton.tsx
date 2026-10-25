import { RefObject, useState } from "react";
import { Cell, exportElement, exportTable } from "../lib/pdf";
import { Icon } from "./ui";
import { useApp } from "./workbenchContext";

export interface TableData { head: Cell[]; rows: Cell[][]; subtitle?: string }

/**
 * One click -> a PDF download. Give it either `table` (a list, exported as a
 * real text table) or `target` (any element, exported as it looks).
 */
export function ExportButton({ title, table, target, label, className = "ibtn", tip }: {
  title: string;
  table?: () => TableData;
  target?: RefObject<HTMLElement | null> | (() => HTMLElement | null);
  label?: string;
  className?: string;
  tip?: string;
}) {
  const [busy, setBusy] = useState(false);
  const app = useApp();
  const go = async () => {
    setBusy(true);
    try {
      if (table) {
        const t = table();
        if (!t.rows.length) throw new Error("nothing to export");
        await exportTable(title, t.head, t.rows, t.subtitle);
      } else {
        const el = typeof target === "function" ? target() : target?.current;
        if (!el) throw new Error("nothing to export");
        await exportElement(el, title);
      }
      app.toast(`Saved “${title}” as PDF`, "ok");
    } catch (e) {
      app.toast(`PDF export failed: ${e instanceof Error ? e.message : String(e)}`, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className={className} data-noexport onClick={go} disabled={busy} title={tip ?? `Export “${title}” to PDF`}>
      <Icon name={busy ? "loading" : "file-pdf"} className={`sm ${busy ? "spin" : ""}`} />{label}
    </button>
  );
}
