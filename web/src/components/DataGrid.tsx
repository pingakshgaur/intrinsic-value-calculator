import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Icon, Popover } from "./ui";
import { ExportButton } from "./ExportButton";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sort?: (row: T) => number | string | null | undefined;
  align?: "r";
  width?: number;
  sticky?: boolean;
  /** shown by default; false = available in the column chooser only */
  visible?: boolean;
  /** cannot be hidden */
  fixed?: boolean;
  /** the value written to a PDF export; defaults to the sort value */
  exportValue?: (row: T) => string | number | null | undefined;
}

/** Rows in the grid's current order. */
export function sortRows<T>(rows: T[], columns: Column<T>[], s: { key: string; asc: boolean } | null) {
  const col = s && columns.find((c) => c.key === s.key);
  if (!s || !col?.sort) return rows;
  const out = [...rows];
  out.sort((a, b) => {
    const x = col.sort!(a);
    const y = col.sort!(b);
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    const c = typeof x === "string" ? x.localeCompare(String(y)) : (x as number) - (y as number);
    return s.asc ? c : -c;
  });
  return out;
}

const fmtCell = (v: unknown) => (typeof v === "number" ? (Number.isInteger(v) ? String(v) : Math.abs(v) < 10 ? v.toFixed(3) : v.toFixed(2)) : v == null ? "" : String(v));

function readPref<T>(key: string, dflt: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : dflt;
  } catch {
    return dflt;
  }
}
function writePref(key: string, v: unknown) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* private mode */ }
}

/** Sort state, hidden columns and density, remembered per grid. */
export function useGridState<T>(id: string, columns: Column<T>[], initialSort?: { key: string; asc: boolean }) {
  const [sort, setSort] = useState(() => readPref(`dg.${id}.sort`, initialSort ?? null));
  const [hidden, setHidden] = useState<string[]>(() => readPref(`dg.${id}.hidden`, columns.filter((c) => c.visible === false).map((c) => c.key)));
  const [dense, setDense] = useState(() => readPref(`dg.${id}.dense`, false));
  useEffect(() => writePref(`dg.${id}.sort`, sort), [id, sort]);
  useEffect(() => writePref(`dg.${id}.hidden`, hidden), [id, hidden]);
  useEffect(() => writePref(`dg.${id}.dense`, dense), [id, dense]);
  return { sort, setSort, hidden, setHidden, dense, setDense };
}

export function GridTools<T>({ columns, state, exportRows, exportTitle }: { columns: Column<T>[]; state: ReturnType<typeof useGridState<T>>; exportRows?: T[]; exportTitle?: string }) {
  const table = () => {
    const cols = columns.filter((c) => (c.fixed || !state.hidden.includes(c.key)) && (c.exportValue || c.sort) && c.header);
    const rows = sortRows(exportRows ?? [], columns, state.sort);
    return { head: cols.map((c) => c.header), rows: rows.map((r) => cols.map((c) => fmtCell((c.exportValue ?? c.sort)!(r)))) };
  };
  return (
    <>
      {exportRows && <ExportButton title={exportTitle ?? "Table"} table={table} />}
      <button className={`ibtn ${state.dense ? "on" : ""}`} title={state.dense ? "Comfortable rows" : "Compact rows"} onClick={() => state.setDense(!state.dense)}>
        <Icon name="list-flat" />
      </button>
      <Popover trigger={(open, toggle) => <button className={`ibtn ${open ? "on" : ""}`} title="Columns" onClick={toggle}><Icon name="settings" /></button>}>
        {() => (
          <>
            <div className="label" style={{ padding: "6px 8px" }}>Columns</div>
            {columns.filter((c) => !c.fixed).map((c) => (
              <label key={c.key}>
                <input type="checkbox" className="cb" checked={!state.hidden.includes(c.key)}
                  onChange={(e) => state.setHidden(e.target.checked ? state.hidden.filter((h) => h !== c.key) : [...state.hidden, c.key])} />
                {c.header}
              </label>
            ))}
          </>
        )}
      </Popover>
    </>
  );
}

export function DataGrid<T>({ rows, columns, rowKey, state, selected, onSelect, onOpen, empty, maxHeight }: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (r: T) => string;
  state: ReturnType<typeof useGridState<T>>;
  selected?: string | null;
  onSelect?: (key: string) => void;
  onOpen?: (key: string) => void;
  empty?: ReactNode;
  maxHeight?: string;
}) {
  const cols = columns.filter((c) => c.fixed || !state.hidden.includes(c.key));
  const sorted = useMemo(() => sortRows(rows, columns, state.sort), [rows, columns, state.sort]);

  const body = useRef<HTMLDivElement>(null);
  const onKey = (e: React.KeyboardEvent) => {
    if (!onSelect || !sorted.length) return;
    const i = sorted.findIndex((r) => rowKey(r) === selected);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = e.key === "ArrowDown" ? Math.min(sorted.length - 1, i + 1) : Math.max(0, i - 1);
      onSelect(rowKey(sorted[n]));
      body.current?.querySelectorAll("tbody tr")[n]?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && selected && onOpen) onOpen(selected);
  };

  return (
    <div className="dg-wrap" ref={body} tabIndex={onSelect ? 0 : undefined} onKeyDown={onKey} style={maxHeight ? { maxHeight } : undefined}>
      <table className={`dg ${state.dense ? "dense" : ""}`}>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className={`${c.sort ? "sortable" : ""} ${c.align === "r" ? "r" : ""} ${c.sticky ? "sticky" : ""}`} style={c.width ? { width: c.width } : undefined}
                onClick={() => c.sort && state.setSort({ key: c.key, asc: state.sort?.key === c.key ? !state.sort.asc : c.key === "company" || c.key === "name" })}>
                {c.header}
                {state.sort?.key === c.key && <Icon name={state.sort.asc ? "arrow-small-up" : "arrow-small-down"} className="xs" style={{ marginLeft: 2, verticalAlign: -2 }} />}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const k = rowKey(r);
            return (
              <tr key={k} className={`${onSelect || onOpen ? "click" : ""} ${k === selected ? "sel" : ""}`}
                onClick={() => onSelect?.(k)} onDoubleClick={() => onOpen?.(k)}>
                {cols.map((c) => <td key={c.key} className={`${c.align === "r" ? "r" : ""} ${c.sticky ? "sticky" : ""}`}>{c.render(r)}</td>)}
              </tr>
            );
          })}
        </tbody>
      </table>
      {!sorted.length && <div style={{ padding: 28, textAlign: "center" }} className="muted">{empty ?? "No rows."}</div>}
    </div>
  );
}
