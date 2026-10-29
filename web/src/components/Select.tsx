import { CSSProperties, Fragment, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useDismiss, usePlacement } from "../lib/popup";
import { Icon } from "./ui";

export interface Opt<T extends string | number> {
  value: T;
  label: ReactNode;
  /** plain text for search and type-ahead when the label is not a string */
  text?: string;
  hint?: ReactNode;
  icon?: string;
  group?: string;
  disabled?: boolean;
}

const textOf = <T extends string | number>(o: Opt<T>) => o.text ?? (typeof o.label === "string" || typeof o.label === "number" ? String(o.label) : String(o.value));

/**
 * The one dropdown of the app: looks like the app's menus in both themes
 * (a native <select> opens an operating-system list), with keyboard support
 * (arrows, Home/End, Enter, Escape, type-ahead) and a filter box for long lists.
 */
export function Select<T extends string | number>({ value, onChange, options, placeholder = "Choose…", size, style, className = "", disabled, title, ariaLabel, searchable, menuWidth }: {
  value: T | null | undefined;
  onChange: (v: T) => void;
  options: Opt<T>[];
  placeholder?: string;
  size?: "sm";
  style?: CSSProperties;
  className?: string;
  disabled?: boolean;
  title?: string;
  ariaLabel?: string;
  /** a filter box; on by default for more than 12 options */
  searchable?: boolean;
  menuWidth?: number;
}) {
  const [open, setOpen] = useState(false);
  const [find, setFind] = useState("");
  const [active, setActive] = useState(0);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const typed = useRef({ s: "", t: 0 });
  const close = useMemo(() => () => { setOpen(false); setFind(""); }, []);
  const refs = useMemo(() => [btn, pop], []);
  useDismiss(open, close, refs as React.RefObject<HTMLElement | null>[]);
  const place = usePlacement(open, btn, pop, "start", 4);
  const filter = searchable ?? options.length > 12;
  const shown = useMemo(() => {
    const f = find.trim().toLowerCase();
    return f ? options.filter((o) => textOf(o).toLowerCase().includes(f)) : options;
  }, [options, find]);
  const current = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const i = Math.max(0, shown.findIndex((o) => o.value === value));
    setActive(i);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (open) list.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" }); }, [active, open]);

  const pick = (o: Opt<T> | undefined) => {
    if (!o || o.disabled) return;
    close();
    btn.current?.focus();
    if (o.value !== value) onChange(o.value);
  };
  const move = (d: number) => {
    if (!shown.length) return;
    let i = active;
    for (let n = 0; n < shown.length; n++) { i = (i + d + shown.length) % shown.length; if (!shown[i].disabled) break; }
    setActive(i);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); setOpen(true); }
      return;
    }
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(shown.length - 1); }
    else if (e.key === "Enter") { e.preventDefault(); pick(shown[active]); }
    else if (e.key === "Escape") { e.preventDefault(); btn.current?.focus(); }  // useDismiss closes it
    else if (e.key === "Tab") close();
    else if (!filter && e.key.length === 1) {
      // type-ahead: jump to the first option starting with what was typed
      const now = Date.now();
      typed.current = { s: (now - typed.current.t < 700 ? typed.current.s : "") + e.key.toLowerCase(), t: now };
      const i = shown.findIndex((o) => textOf(o).toLowerCase().startsWith(typed.current.s));
      if (i >= 0) setActive(i);
    }
  };

  let lastGroup: string | undefined;
  return (
    <>
      <button ref={btn} type="button" className={`sel dd ${size ?? ""} ${open ? "open" : ""} ${className}`} style={style} disabled={disabled} title={title}
        aria-haspopup="listbox" aria-expanded={open} aria-label={ariaLabel} onClick={() => (open ? close() : setOpen(true))} onKeyDown={onKey}>
        {current?.icon && <Icon name={current.icon} className="xs" />}
        <span className={`dd-v ${current ? "" : "faint"}`}>{current ? current.label : placeholder}</span>
        <Icon name="chevron-down" className="xs dd-chev" />
      </button>
      {open && createPortal(
        <div ref={pop} className="menu dd-menu" style={{ ...place, minWidth: Math.max(menuWidth ?? 0, btn.current?.offsetWidth ?? 0) }} onKeyDown={onKey}>
          {filter && (
            <div className="dd-find"><Icon name="search" className="xs" />
              <input autoFocus value={find} placeholder="Filter…" onChange={(e) => { setFind(e.target.value); setActive(0); }} aria-label="Filter the options" /></div>
          )}
          <div ref={list} className="dd-list" role="listbox" aria-label={ariaLabel ?? title}>
            {shown.map((o, i) => {
              const head = o.group && o.group !== lastGroup ? o.group : null;
              lastGroup = o.group;
              return (
                <Fragment key={String(o.value)}>
                  {head && <div className="label dd-group">{head}</div>}
                  <button type="button" role="option" aria-selected={o.value === value} data-i={i} disabled={o.disabled}
                    className={`dd-opt ${i === active ? "active" : ""} ${o.value === value ? "on" : ""}`}
                    onMouseEnter={() => setActive(i)} onClick={() => pick(o)}>
                    <Icon name="check" className={`xs dd-check ${o.value === value ? "" : "hide"}`} />
                    {o.icon && <Icon name={o.icon} className="xs" />}
                    <span className="grow ellipsis">{o.label}</span>
                    {o.hint != null && <span className="dd-hint">{o.hint}</span>}
                  </button>
                </Fragment>
              );
            })}
            {!shown.length && <div className="dd-none xs faint">Nothing matches “{find}”.</div>}
          </div>
        </div>, document.body)}
    </>
  );
}

export interface ActionItem { label: ReactNode; onClick: () => void; icon?: string; hint?: ReactNode; disabled?: boolean; danger?: boolean; group?: string }

/** A button that opens a menu of actions, in the same look as every other menu ("Copy to…", "Research…"). */
export function ActionMenu({ label, icon, items, disabled, small, secondary = true, title, empty }: {
  label: ReactNode; icon?: string; items: ActionItem[]; disabled?: boolean; small?: boolean; secondary?: boolean; title?: string; empty?: string;
}) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const close = useMemo(() => () => setOpen(false), []);
  const refs = useMemo(() => [btn, pop], []);
  useDismiss(open, close, refs as React.RefObject<HTMLElement | null>[]);
  const place = usePlacement(open, btn, pop, "start", 4);
  let lastGroup: string | undefined;
  return (
    <>
      <button ref={btn} type="button" className={`btn ${secondary ? "sec" : ""} ${small ? "sm" : ""} ${open ? "on" : ""}`} disabled={disabled} title={title}
        aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        {icon && <Icon name={icon} className="sm" />}{label}<Icon name="chevron-down" className="xs" />
      </button>
      {open && createPortal(
        <div ref={pop} className="menu" role="menu" style={place}>
          {items.map((it, i) => {
            const head = it.group && it.group !== lastGroup ? it.group : null;
            lastGroup = it.group;
            return (
              <Fragment key={i}>
                {head && <div className="label dd-group">{head}</div>}
                <button type="button" role="menuitem" disabled={it.disabled} className={it.danger ? "danger" : ""} onClick={() => { close(); it.onClick(); }}>
                  {it.icon && <Icon name={it.icon} className="sm" />}<span className="grow ellipsis">{it.label}</span>{it.hint != null && <span className="dd-hint">{it.hint}</span>}
                </button>
              </Fragment>
            );
          })}
          {!items.length && <div className="dd-none xs faint">{empty ?? "Nothing to choose."}</div>}
        </div>, document.body)}
    </>
  );
}

/**
 * Type freely or pick a suggestion - the same list as Select, filtered by
 * what is typed, where a new value is fine too.
 */
export function Combobox({ value, onChange, suggestions, placeholder, className = "", style, ariaLabel }: {
  value: string; onChange: (v: string) => void; suggestions: string[]; placeholder?: string; className?: string; style?: CSSProperties; ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const inp = useRef<HTMLInputElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const close = useMemo(() => () => { setOpen(false); setActive(-1); }, []);
  const refs = useMemo(() => [inp, pop], []);
  useDismiss(open, close, refs as React.RefObject<HTMLElement | null>[]);
  const place = usePlacement(open, inp, pop, "start", 4);
  const v = value.trim().toLowerCase();
  const shown = suggestions.filter((s) => !v || (s.toLowerCase().includes(v) && s.toLowerCase() !== v)).slice(0, 50);
  const pick = (s: string) => { onChange(s); close(); };
  return (
    <>
      <input ref={inp} className={`inp ${className}`} style={style} value={value} placeholder={placeholder} aria-label={ariaLabel} aria-autocomplete="list" aria-expanded={open && shown.length > 0}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(-1); }} onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(shown.length - 1, a + 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(-1, a - 1)); }
          else if (e.key === "Enter" && open && active >= 0 && shown[active]) { e.preventDefault(); pick(shown[active]); }
          else if (e.key === "Tab") close();
        }} />
      {open && shown.length > 0 && createPortal(
        <div ref={pop} className="menu dd-menu" style={{ ...place, minWidth: inp.current?.offsetWidth ?? 0 }}>
          <div className="dd-list" role="listbox">
            {shown.map((s, i) => (
              <button key={s} type="button" role="option" aria-selected={i === active} className={`dd-opt ${i === active ? "active" : ""}`}
                onMouseEnter={() => setActive(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(s)}>
                <span className="grow ellipsis">{s}</span>
              </button>
            ))}
          </div>
        </div>, document.body)}
    </>
  );
}
