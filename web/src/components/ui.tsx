import { Component, ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { UseQueryResult } from "@tanstack/react-query";
import { LABEL_COLOR } from "../lib/labels";
import { isNum, money } from "../lib/format";

export function Icon({ name, className = "", title, style }: { name: string; className?: string; title?: string; style?: React.CSSProperties }) {
  return <i className={`codicon codicon-${name} ${className}`} title={title} aria-hidden={title ? undefined : true} style={style} />;
}

export function Panel({ title, meta, tools, children, flush, className = "", style, id }: {
  title?: ReactNode; meta?: ReactNode; tools?: ReactNode; children: ReactNode; flush?: boolean; className?: string; style?: React.CSSProperties; id?: string;
}) {
  return (
    <section className={`panel ${className}`} style={style} id={id}>
      {(title || tools) && (
        <header className="panel-h">
          {title && <h3>{title}</h3>}
          {meta && <span className="meta">{meta}</span>}
          {tools && <div className="tools">{tools}</div>}
        </header>
      )}
      <div className={`panel-b ${flush ? "flush" : ""}`}>{children}</div>
    </section>
  );
}

export function PageHeader({ crumbs, title, sub, actions }: { crumbs?: { label: string; to?: string }[]; title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="ph">
      <div style={{ minWidth: 0 }}>
        {crumbs && (
          <div className="crumbs">
            {crumbs.map((c, i) => (
              <span key={i} className="row" style={{ gap: 6 }}>
                {i > 0 && <Icon name="chevron-right" className="xs" />}
                {c.to ? <Link to={c.to}>{c.label}</Link> : <span>{c.label}</span>}
              </span>
            ))}
          </div>
        )}
        <h1>{title}</h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
      {actions && <div className="acts">{actions}</div>}
    </div>
  );
}

export function Empty({ icon = "inbox", title, children, action }: { icon?: string; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="ico"><Icon name={icon} /></div>
      <h3>{title}</h3>
      {children && <div style={{ maxWidth: 460 }} className="small">{children}</div>}
      {action && <div style={{ marginTop: 6 }}>{action}</div>}
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error ?? "Unknown error");
  return (
    <div className="note err">
      <Icon name="error" />
      <div className="grow">{msg}</div>
      {onRetry && <button className="btn xs sec" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function Skeleton({ h = 12, w = "100%" }: { h?: number; w?: number | string }) {
  return <div className="skel" style={{ height: h, width: w }} />;
}

export function Loading({ rows = 6 }: { rows?: number }) {
  return (
    <div className="col" style={{ padding: 16, gap: 10 }}>
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} h={i === 0 ? 18 : 11} w={i === 0 ? "30%" : `${94 - ((i * 13) % 32)}%`} />)}
    </div>
  );
}

export function QueryView<T>({ q, children, rows }: { q: UseQueryResult<T>; children: (data: T) => ReactNode; rows?: number }) {
  if (q.isLoading || (q.data === undefined && !q.isError)) return <Loading rows={rows} />;
  if (q.isError) return <div style={{ padding: 4 }}><ErrorNote error={q.error} onRetry={() => q.refetch()} /></div>;
  return <>{children(q.data as T)}</>;
}

export function LabelBadge({ label }: { label: string | null | undefined }) {
  const l = label || "Insufficient evidence";
  return <span className="badge" style={{ color: LABEL_COLOR[l] ?? "var(--fg-2)" }}><span className="d" />{l}</span>;
}

export function Diverge({ value, width = 90, max = 1 }: { value: number | null | undefined; width?: number | string; max?: number }) {
  const v = isNum(value) ? Math.max(-max, Math.min(max, value)) / max : 0;
  const color = v > 0.05 ? "var(--up)" : v < -0.05 ? "var(--down)" : "var(--fg-3)";
  const half = 50 * Math.abs(v);
  return (
    <div className="dv" style={{ width }} title={isNum(value) ? value.toFixed(3) : "n/a"}>
      <span style={{ left: v >= 0 ? "50%" : `${50 - half}%`, width: `${half}%`, background: color }} />
    </div>
  );
}

export function Meter({ value, max = 100, width = 64, color }: { value: number | null | undefined; max?: number; width?: number | string; color?: string }) {
  const v = isNum(value) ? Math.max(0, Math.min(1, value / max)) : 0;
  const c = color ?? (v >= 0.6 ? "var(--up)" : v >= 0.35 ? "var(--c-yellow)" : "var(--down)");
  return <div className="meter" style={{ width }}><span style={{ width: `${v * 100}%`, background: c }} /></div>;
}

/** Bear-to-bull band with the HYBRID MODEL value and the price, on a scale. */
export function RangeBar({ low, high, value, price, min, max, width = 120 }: { low: number | null; high: number | null; value: number | null; price: number | null; min: number; max: number; width?: number }) {
  const x = (v: number) => `${Math.max(0, Math.min(100, ((v - min) / (max - min || 1)) * 100))}%`;
  return (
    <div className="rangebar" style={{ width }} title={`range ${money(low, 0)} – ${money(high, 0)} · value ${money(value, 0)} · price ${money(price, 0)}`}>
      {isNum(low) && isNum(high) && <span className="rb" style={{ left: x(low), width: `calc(${x(high)} - ${x(low)})` }} />}
      {isNum(value) && <span className="rv" style={{ left: x(value) }} />}
      {isNum(price) && <span className="rp" style={{ left: x(price) }} />}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string; icon?: string; count?: number }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={t.id === value} className={t.id === value ? "on" : ""} onClick={() => onChange(t.id)}>
          {t.icon && <Icon name={t.icon} className="sm" />}{t.label}{t.count != null && <span className="n">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <label className="tg" style={disabled ? { cursor: "default", opacity: 0.6 } : undefined}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="t" />
      {label && <span>{label}</span>}
    </label>
  );
}

export function Drawer({ title, icon, onClose, children, wide, footer, actions }: { title: ReactNode; icon?: string; onClose: () => void; children: ReactNode; wide?: boolean; footer?: ReactNode; actions?: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <>
      <div className="scrim" onMouseDown={onClose} />
      <aside className={`drawer ${wide ? "wide" : ""}`} role="dialog">
        <div className="drawer-h">
          {icon && <Icon name={icon} />}<h2>{title}</h2><span className="spacer" />{actions}
          <button className="ibtn" onClick={onClose} title="Close (Esc)"><Icon name="close" /></button>
        </div>
        <div className="drawer-b">{children}</div>
        {footer && <div className="drawer-f">{footer}</div>}
      </aside>
    </>
  );
}

/** Click-outside popover anchored to its trigger. */
export function Popover({ trigger, children, className = "menu" }: { trigger: (open: boolean, toggle: () => void) => ReactNode; children: (close: () => void) => ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const k = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", h);
    window.addEventListener("keydown", k);
    return () => { document.removeEventListener("mousedown", h); window.removeEventListener("keydown", k); };
  }, [open]);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      {trigger(open, () => setOpen((o) => !o))}
      {open && <div className={className}>{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function Tip({ active, payload, label, fmt, title }: {
  active?: boolean; payload?: { name?: string; value?: unknown; color?: string }[]; label?: ReactNode; fmt?: (v: unknown, name?: string) => string; title?: (l: ReactNode) => ReactNode;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tt">{title ? title(label) : label}</div>
      {payload.filter((p) => p.value != null).map((p, i) => (
        <div className="tr" key={i}>
          <span className="row" style={{ gap: 6 }}><span className="sw" style={{ background: p.color }} />{p.name}</span>
          <span className="mono strong">{fmt ? fmt(p.value, p.name) : String(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null; key?: string }> {
  state: { error: Error | null; key?: string } = { error: null, key: this.props.resetKey };
  static getDerivedStateFromProps(p: { resetKey?: string }, s: { error: Error | null; key?: string }) {
    return p.resetKey !== s.key ? { error: null, key: p.resetKey } : null;
  }
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error) { console.error("view crashed", error); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page">
        <Panel>
          <Empty icon="bug" title="This view hit an unexpected problem" action={<button className="btn sec" onClick={() => this.setState({ error: null })}>Try again</button>}>
            The rest of the application keeps working.
            <pre className="mono" style={{ textAlign: "left", whiteSpace: "pre-wrap", color: "var(--error)", marginTop: 8 }}>{this.state.error.message}</pre>
          </Empty>
        </Panel>
      </div>
    );
  }
}
