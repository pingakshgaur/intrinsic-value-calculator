import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useJobs, useMarket, useStatus } from "../lib/hooks";
import { useWatchlist } from "../lib/live";
import { ScopeProvider } from "../lib/scope";
import { ScopePicker } from "./ScopePicker";
import { setTheme, useTheme } from "../lib/theme";
import { ago, isNum, num, pct } from "../lib/format";
import { Glossary } from "./Glossary";
import { Tour, TourStart } from "./Tour";
import { CommandPalette } from "./CommandPalette";
import { Notifications } from "./Notifications";
import { RunMonitor } from "./JobLog";
import { Drawer, ErrorBoundary, Icon } from "./ui";
import { AppContext, Toast } from "./workbenchContext";

const NAV = [
  { group: "Analysis", items: [
    { to: "/dashboard", icon: "dashboard", label: "Dashboard" },
    { to: "/", icon: "pulse", label: "Command Center", end: true },
    { to: "/markets", icon: "graph", label: "Markets", badge: "LIVE" },
    { to: "/watchlist", icon: "eye", label: "Watchlists" },
    { to: "/studio", icon: "beaker", label: "HYBRID MODEL Studio" },
  ] },
  { group: "Research workforce", items: [
    { to: "/agents", icon: "organization", label: "Overview", end: true },
    { to: "/agents/network", icon: "type-hierarchy", label: "Agent Network" },
    { to: "/agents/chat", icon: "comment-discussion", label: "Research Room" },
  ] },
  { group: "Operations", items: [
    { to: "/operations", icon: "server-process", label: "Operations" },
    { to: "/performance", icon: "graph-line", label: "Model Performance" },
    { to: "/configuration", icon: "settings", label: "Configuration" },
  ] },
];

const TAPE: Record<string, { k: string; fmt: (v: number) => string }> = {
  nifty: { k: "NIFTY 50", fmt: (v) => num(v, 0) },
  india_vix: { k: "INDIA VIX", fmt: (v) => num(v, 2) },
  usd_inr: { k: "USD/INR", fmt: (v) => num(v, 2) },
  brent: { k: "BRENT", fmt: (v) => "$" + num(v, 1) },
  us_10y: { k: "US 10Y", fmt: (v) => num(v, 2) + "%" },
  gold: { k: "GOLD", fmt: (v) => "$" + num(v, 0) },
};

export const JOB_TITLE: Record<string, string> = { agents: "Research", valuation: "Valuation report", screen: "Data check", llm_check: "AI key check", learn: "Learning pool refresh" };
export function jobTitle(kind: string, opts: Record<string, unknown> | null | undefined) {
  if (kind === "agents" && opts?.auto) return opts.quick ? "Workforce sweep (auto)" : "Workforce research (auto)";
  const on = opts?.watchlist_name ? ` · ${String(opts.watchlist_name)}` : "";
  if (kind === "agents") return (opts?.quick ? "Quick sweep" : "Full research") + on;
  if (kind === "valuation" && opts?.auto_train) return "Valuation + auto-train";
  if (kind === "valuation") return "Valuation report" + on;
  if (kind === "learn") return opts?.retrain ? "Learning pool refresh + retrain" : opts?.auto ? "Evening learning pool refresh" : "Learning pool refresh";
  return JOB_TITLE[kind] ?? kind;
}

function ThemeToggle() {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button className="tool themer" title={`Switch to ${next} mode`} aria-label={`Switch to ${next} mode`}
      onClick={(e) => setTheme(next, e.currentTarget)}>
      <svg className="sun" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <circle cx="12" cy="12" r="4.2" />
        {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => <line key={a} x1="12" y1="2.6" x2="12" y2="4.8" transform={`rotate(${a} 12 12)`} />)}
      </svg>
      <svg className="moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
        <path d="M20.5 14.2A8.6 8.6 0 1 1 9.8 3.5a7 7 0 0 0 10.7 10.7z" />
      </svg>
    </button>
  );
}

export function Shell() {
  const nav = useNavigate();
  const loc = useLocation();
  const status = useStatus();
  const market = useMarket();
  const active = status.data?.active_job ?? null;
  const jobs = useJobs(!!active);
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("frame.collapsed") === "1"; } catch { return false; } });
  // a narrow window gets the icon rail automatically, without changing the saved choice
  const [narrow, setNarrow] = useState(() => window.innerWidth < 900);
  useEffect(() => {
    const on = () => setNarrow(window.innerWidth < 900);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  const [runDrawer, setRunDrawer] = useState<string | null | false>(false);
  const [glossary, setGlossary] = useState(false);
  const [palette, setPalette] = useState(false);
  const [tour, setTour] = useState<(TourStart & { n: number }) | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((text: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  const showJob = useCallback((id: string) => setRunDrawer(id), []);
  const openHelp = useCallback(() => setGlossary(true), []);
  const startTour = useCallback((o: TourStart = {}) => { setGlossary(false); setRunDrawer(false); setTour({ ...o, n: Date.now() }); }, []);
  const ctx = useMemo(() => ({ toast, showJob, openHelp, startTour }), [toast, showJob, openHelp, startTour]);

  useEffect(() => { try { localStorage.setItem("frame.collapsed", collapsed ? "1" : "0"); } catch { /* ignore */ } }, [collapsed]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(true); }
      else if ((e.ctrlKey || e.metaKey) && e.key === "\\") { e.preventDefault(); setCollapsed((c) => !c); }
      else if (!typing && e.key === "?") setGlossary(true);
      else if (e.altKey && /^[1-9]$/.test(e.key)) { e.preventDefault(); nav(NAV.flatMap((g) => g.items)[Number(e.key) - 1].to); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nav]);

  const wl = useWatchlist();
  const tracker = wl.data?.tracker;
  const keys = status.data?.keys ?? {};
  const llm = status.data?.llm ?? { ready: ["GROQ_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY"].filter((k) => keys[k]).length, total: 3, keys: 0 };
  const lastJob = jobs.data?.[0];
  const offline = status.isError;

  return (
    <AppContext.Provider value={ctx}>
      <ScopeProvider>
      <div className={`frame ${collapsed || narrow ? "collapsed" : ""}`}>
        <aside className="sidebar">
          <div className="sb-brand">
            <span className="sb-logo"><i /></span>
            <span className="sb-name">INTVAL</span>
            <span className="sb-env">NSE · INR</span>
          </div>
          <nav className="sb-nav" aria-label="Main">
            {NAV.map((g) => (
              <div className="sb-group" key={g.group}>
                <div className="label">{g.group}</div>
                {g.items.map((it) => (
                  <NavLink key={it.to} to={it.to} end={it.end} className={({ isActive }) => `sb-item ${isActive ? "active" : ""}`} title={it.label}>
                    <Icon name={it.icon} />
                    <span>{it.label}</span>
                    {"badge" in it && it.badge && <span className="tagnew">{it.badge}</span>}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
          <div className="sb-foot">
            <SystemStatus rows={[
              { k: "Server", v: offline ? "offline" : "local", tone: offline ? "bad" : "ok" },
              { k: "AI providers", v: `${llm.ready}/${llm.total}${llm.keys > llm.ready ? ` · ${llm.keys} keys` : ""}`, tone: llm.ready ? "ok" : "" },
              { k: "Report", v: ago(status.data?.valuation_updated), tone: "" },
              { k: "Research", v: ago(status.data?.intel_updated), tone: "" },
              { k: "Tracker", v: !tracker ? "—" : tracker.paused ? "paused" : `${wl.data?.items.length ?? 0} live`, title: tracker?.error ?? undefined,
                tone: tracker?.error ? "bad" : tracker && !tracker.paused && (wl.data?.items.length ?? 0) > 0 ? (tracker.market.state === "closed" ? "ok" : "busy") : "" },
            ]} />
            <button className="ibtn sb-collapse" onClick={() => setCollapsed(true)} title="Collapse the sidebar (Ctrl \)"><Icon name="layout-sidebar-left-off" /></button>
          </div>
          {collapsed && <button className="ibtn" style={{ margin: "0 auto 12px" }} title="Expand (Ctrl \)" onClick={() => setCollapsed(false)}><Icon name="layout-sidebar-left" /></button>}
        </aside>

        <header className="topbar">
          <div className="tape" aria-label="Market">
            {(market.data ?? []).map((t) => {
              const m = TAPE[t.name];
              if (!m || !isNum(t.last)) return null;
              const d = t.chg_1m;
              return (
                <div className="tape-item" key={t.name} title={`${t.ticker} · ${t.date} · 1M ${pct(t.chg_1m, 1, true)} · 1Y ${pct(t.chg_1y, 1, true)}`}>
                  <span className="k">{m.k}</span>
                  <span className="v">{m.fmt(t.last)}</span>
                  {isNum(d) && <span className={`d ${d >= 0 ? "up" : "down"}`}>{d >= 0 ? "▲" : "▼"}{pct(Math.abs(d), 1)}</span>}
                </div>
              );
            })}
            {market.isLoading && <div className="tape-item"><span className="k">MARKET</span><span className="faint">loading…</span></div>}
            {market.data && !market.data.length && <div className="tape-item"><span className="k">MARKET</span><span className="faint">data unavailable</span></div>}
            {(market.data?.length ?? 0) > 0 && <div className="tape-item" style={{ borderRight: 0 }}><span className="faint xs">1-month change</span></div>}
          </div>
          <div className="top-tools">
            <ThemeToggle />
            <ScopePicker />
            <button className="cmdk" onClick={() => setPalette(true)} aria-label="Search companies, actions"><Icon name="search" className="sm" /><span>Search companies, actions…</span><kbd>Ctrl K</kbd></button>
            <Notifications />
            <button className="tool" title="Glossary (?)" onClick={() => setGlossary(true)}><Icon name="question" /></button>
            <button className={`runchip ${active ? "busy" : ""}`} onClick={() => setRunDrawer(active?.id ?? lastJob?.id ?? null)} title="Runs">
              <span className={`dot ${active ? "busy" : lastJob?.status === "failed" ? "bad" : lastJob ? "ok" : ""}`} />
              <span className="rc-t">{active ? <>{jobTitle(active.kind, active.opts)}<span className="bar"><span className="indet" /></span></> : lastJob ? `Last run ${ago(lastJob.finished ?? lastJob.started)}` : "No runs"}</span>
            </button>
          </div>
        </header>

        <main className="main">
          {offline && (
            <div className="note err" style={{ borderRadius: 0, borderLeft: 0, borderRight: 0, borderTop: 0 }}>
              <Icon name="debug-disconnect" /><div>The local server is not answering. Start it with <span className="mono">python run.py --web</span>; this page reconnects by itself.</div>
            </div>
          )}
          <ErrorBoundary resetKey={loc.pathname}><Outlet /></ErrorBoundary>
        </main>
      </div>

      {runDrawer !== false && (
        <Drawer title="Runs" icon="server-process" onClose={() => setRunDrawer(false)}
          actions={<button className="btn sm sec" onClick={() => { setRunDrawer(false); nav(`/operations${runDrawer ? `?job=${runDrawer}` : ""}`); }}>Open Operations</button>}>
          <RunMonitor jobId={runDrawer} compact />
          {(jobs.data?.length ?? 0) > 0 && (
            <div className="col" style={{ gap: 2 }}>
              <div className="label" style={{ marginBottom: 4 }}>Recent</div>
              {jobs.data!.slice(0, 8).map((j) => (
                <button key={j.id} className={`btn ghost sm ${j.id === runDrawer ? "sec" : ""}`} style={{ justifyContent: "flex-start" }} onClick={() => setRunDrawer(j.id)}>
                  <span className={`dot ${j.status === "running" ? "busy" : j.status === "succeeded" ? "ok" : j.status === "failed" ? "bad" : ""}`} />
                  <span className="grow ellipsis" style={{ textAlign: "left" }}>{jobTitle(j.kind, j.opts)}</span>
                  <span className="faint xs">{ago(j.started)}</span>
                </button>
              ))}
            </div>
          )}
        </Drawer>
      )}
      {glossary && (
        <Drawer title="Glossary" icon="book" onClose={() => setGlossary(false)}>
          <button className="gl-tour" onClick={() => startTour()}><Icon name="compass" /><span><b>New here? Take the guided tour</b><span className="xs faint">A few minutes across every page · or search “onboarding”</span></span><Icon name="arrow-right" className="sm" /></button>
          <Glossary onNavigate={() => setGlossary(false)} />
        </Drawer>
      )}
      {palette && <CommandPalette onClose={() => setPalette(false)} />}
      {tour && <Tour key={tour.n} start={tour} onClose={() => setTour(null)} openHelp={openHelp} />}
      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`note ${t.tone === "error" ? "err" : t.tone === "ok" ? "ok" : "inf"}`}>
            <Icon name={t.tone === "error" ? "error" : t.tone === "ok" ? "pass" : "info"} /><div>{t.text}</div>
          </div>
        ))}
      </div>
      </ScopeProvider>
    </AppContext.Provider>
  );
}

interface StatusRow { k: string; v: string; tone: "ok" | "bad" | "busy" | ""; title?: string }

/** Server, AI, report, research and tracker status as one line of dots; click for the details. */
function SystemStatus({ rows }: { rows: StatusRow[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [open]);
  const bad = rows.filter((r) => r.tone === "bad").length;
  return (
    <div className="sb-sys" ref={ref}>
      {open && (
        <div className="sb-sys-pop" role="dialog" aria-label="System status">
          {rows.map((r) => <div key={r.k} className="r" title={r.title}><span className={`dot ${r.tone}`} />{r.k}<b>{r.v}</b></div>)}
        </div>
      )}
      <button className={`sb-sys-btn ${open ? "on" : ""}`} onClick={() => setOpen(!open)} aria-expanded={open} title="System status">
        <span className="dots">{rows.map((r) => <span key={r.k} className={`dot ${r.tone}`} />)}</span>
        <span className="t">{bad ? `${bad} issue${bad > 1 ? "s" : ""}` : "System"}</span>
        <Icon name={open ? "chevron-down" : "chevron-up"} className="xs" />
      </button>
    </div>
  );
}
