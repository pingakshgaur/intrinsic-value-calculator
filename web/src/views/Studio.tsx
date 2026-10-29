import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ParamDef, ParamGroup, PortfolioRow, Simulation } from "../lib/api";
import { useLabCompanies } from "../lib/hooks";
import { crore, isNum, money, pct, shortName, slug, titleCase } from "../lib/format";
import { LABEL_HEX } from "../lib/labels";
import { Empty, ErrorNote, Icon, LabelBadge, Loading, PageHeader, Panel, Popover, Toggle } from "../components/ui";
import { Bridge, LensContribution, RangeLegend, ValueRange } from "../components/charts";
import { Column, DataGrid, useGridState } from "../components/DataGrid";
import { RunButton } from "../components/RunButton";
import { useApp } from "../components/workbenchContext";
import { Select } from "../components/Select";
import { companyPath } from "../lib/company";

type Overrides = Record<string, number | boolean>;
const CUR = "studio.overrides.v1";
const SETS = "studio.sets.v1";
const PANELS = "studio.panels.v1";

function load<T>(k: string, d: T): T { try { const v = JSON.parse(localStorage.getItem(k) || "null"); return v ?? d; } catch { return d; } }
function save(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } }
function useDebounced<T>(v: T, ms: number) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = window.setTimeout(() => setD(v), ms); return () => window.clearTimeout(t); }, [v, ms]);
  return d;
}
const same = (a: unknown, b: unknown) => (isNum(a) && isNum(b) ? Math.abs(a - b) < 1e-9 : a === b);

function show(p: ParamDef | undefined, v: unknown) {
  if (typeof v === "boolean") return v ? "on" : "off";
  if (!isNum(v)) return "—";
  if (p?.kind === "pct") return (v * 100).toFixed(2) + "%";
  if (p?.kind === "int") return String(Math.round(v));
  return v.toFixed(2);
}

export function Studio() {
  const [params, setParams] = useSearchParams();
  const companies = useLabCompanies();
  const schema = useQuery({ queryKey: ["hm-params"], queryFn: () => api.post<ParamGroup[]>("/api/hybrid/params", {}) });
  const [overrides, setOverrides] = useState<Overrides>(() => load(CUR, {}));
  const [sets, setSets] = useState<Record<string, Overrides>>(() => load(SETS, {}));
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const qc = useQueryClient();
  const app = useApp();
  useEffect(() => save(CUR, overrides), [overrides]);
  useEffect(() => save(SETS, sets), [sets]);
  // the side panels open and close; the canvas takes the room they leave
  const [panels, setPanels] = useState<{ left: boolean; right: boolean }>(() => ({ left: true, right: true, ...load(PANELS, {}) }));
  useEffect(() => save(PANELS, panels), [panels]);
  const toggle = (side: "left" | "right", v?: boolean) => setPanels((p) => ({ ...p, [side]: v ?? !p[side] }));
  const leftOpen = useRef(panels.left);
  leftOpen.current = panels.left;
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || (e.target instanceof Element && e.target.closest("input, textarea, select, [contenteditable]"))) return;
      if (e.key === "[") toggle("left");
      else if (e.key === "]") toggle("right");
    };
    // a click in the sensitivity chart focuses a parameter: open the parameter panel first
    const f = (e: Event) => {
      if (leftOpen.current) return;
      toggle("left", true);
      const path = (e as CustomEvent<string>).detail;
      window.setTimeout(() => window.dispatchEvent(new CustomEvent("studio:focus", { detail: path })), 120);
    };
    window.addEventListener("keydown", k);
    window.addEventListener("studio:focus", f);
    return () => { window.removeEventListener("keydown", k); window.removeEventListener("studio:focus", f); };
  }, []);

  const mode = params.get("mode") === "portfolio" ? "portfolio" : "company";
  const list = companies.data ?? [];
  const cur = params.get("company");
  const company = cur && list.some((c) => c.company === cur) ? cur : list.find((c) => c.source === "research")?.company ?? list[0]?.company ?? "";
  const setQ = (k: string, v: string) => { const p = new URLSearchParams(params); p.set(k, v); setParams(p, { replace: true }); };

  const byPath = useMemo(() => {
    const m: Record<string, ParamDef> = {};
    for (const g of schema.data ?? []) for (const p of g.params) m[p.path] = p;
    return m;
  }, [schema.data]);
  const effective = useMemo(() => {
    const o: Overrides = {};
    for (const [k, v] of Object.entries(overrides)) if (byPath[k] && byPath[k].value !== v) o[k] = v;
    return o;
  }, [overrides, byPath]);
  const dirty = Object.keys(effective).length;
  // constants whose saved value (or pending change) differs from the shipped default
  const offDefault = useMemo(() => {
    const o: Overrides = {};
    for (const p of Object.values(byPath)) {
      if (p.default == null) continue;
      const cur = p.path in overrides ? overrides[p.path] : p.value;
      if (!same(cur, p.default)) o[p.path] = p.default;
    }
    return o;
  }, [byPath, overrides]);
  const restoreDefaults = () => {
    const n = Object.keys(offDefault).length;
    setOverrides({ ...overrides, ...offDefault });
    app.toast(`${n} constant(s) set back to their defaults. Review the effect, then Commit to save.`, "ok");
  };

  const commit = async () => {
    setSaving(true);
    try {
      await api.post("/api/hybrid/save", { overrides: effective });
      await qc.invalidateQueries({ queryKey: ["hm-params"] });
      qc.invalidateQueries({ queryKey: ["lab-companies"] });
      setOverrides({});
      setConfirm(false);
      app.toast(`${dirty} constant(s) saved to the HYBRID MODEL. Re-run the report or research to refresh stored values.`, "ok");
    } catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); } finally { setSaving(false); }
  };

  return (
    <div className="page fill studio-page">
      <PageHeader
        crumbs={[{ label: "Analysis" }, { label: "HYBRID MODEL Studio" }]}
        title={<span className="row" style={{ gap: 10 }}>HYBRID MODEL Studio <span className="tag hm">live</span></span>}
        sub="Change any constant and see the value, range, lenses and bridge respond instantly. Nothing is written until you commit."
        actions={
          <>
            <div className="seg" aria-label="Panels">
              <button className={panels.left ? "on" : ""} onClick={() => toggle("left")} title={`${panels.left ? "Hide" : "Show"} the parameters ([)`}><Icon name="layout-sidebar-left" className="sm" /></button>
              <button className={panels.right ? "on" : ""} onClick={() => toggle("right")} title={`${panels.right ? "Hide" : "Show"} the inspector (])`}><Icon name="layout-sidebar-right" className="sm" /></button>
            </div>
            <div className="seg">
              <button className={mode === "company" ? "on" : ""} onClick={() => setQ("mode", "company")}><Icon name="symbol-class" className="sm" />Company</button>
              <button className={mode === "portfolio" ? "on" : ""} onClick={() => setQ("mode", "portfolio")}><Icon name="layers" className="sm" />Portfolio</button>
            </div>
            <ScenarioMenu sets={sets} setSets={setSets} current={effective} onLoad={(o) => setOverrides(o)} />
            <button className="btn ghost" disabled={!dirty} onClick={() => setOverrides({})} title="Discard the changes you have not committed"><Icon name="discard" className="sm" />Discard</button>
            <button className="btn sec" disabled={!Object.keys(offDefault).length} onClick={restoreDefaults}
              title="Load the shipped default for every constant you changed - preview first, nothing is written until you commit">
              <Icon name="history" className="sm" />Defaults{Object.keys(offDefault).length ? ` (${Object.keys(offDefault).length})` : ""}
            </button>
            {confirm ? (
              <>
                <span className="small muted">Write {dirty} change(s) to agent_settings.yaml?</span>
                <button className="btn sec" onClick={() => setConfirm(false)}>Cancel</button>
                <button className="btn" disabled={saving} onClick={commit}><Icon name={saving ? "loading" : "check"} className={`sm ${saving ? "spin" : ""}`} />Confirm</button>
              </>
            ) : <button className="btn" disabled={!dirty} onClick={() => setConfirm(true)}><Icon name="git-commit" className="sm" />Commit {dirty > 0 ? `(${dirty})` : ""}</button>}
          </>
        }
      />
      {(companies.isError || schema.isError) && <ErrorNote error={companies.error ?? schema.error} />}
      {companies.isLoading || schema.isLoading ? <Loading rows={12} /> : !list.length ? (
        <Panel><Empty icon="beaker" title="Nothing to model yet" action={<RunButton kind="valuation" label="Run valuation report" icon="graph" />}>The Studio needs each company's HYBRID MODEL inputs, written by the valuation report or a research run.</Empty></Panel>
      ) : (
        <div className={`studio ${panels.left ? "" : "no-left"} ${panels.right || mode !== "company" ? "" : "no-right"}`}>
          {panels.left ? (
            <section>
              <div className="pane-h"><h3>Parameters</h3><span className="spacer" />{dirty > 0 && <span className="tag hm">{dirty} changed</span>}
                <button className="ibtn sm" onClick={() => toggle("left", false)} title="Hide the parameters ([)"><Icon name="chevron-left" className="xs" /></button></div>
              <ParamTree groups={schema.data ?? []} overrides={overrides} effective={effective} setOverrides={setOverrides} />
            </section>
          ) : (
            <button className="studio-tab" onClick={() => toggle("left", true)} title="Show the parameters ([)">
              <Icon name="chevron-right" className="xs" /><span>Parameters</span>{dirty > 0 && <b className="tag hm">{dirty}</b>}
            </button>
          )}
          {mode === "company"
            ? <CompanyCanvas company={company} list={list} onPick={(c) => setQ("company", c)} overrides={effective} byPath={byPath} setOverrides={setOverrides}
                right={panels.right} setRight={(v) => toggle("right", v)} />
            : <Portfolio overrides={effective} />}
        </div>
      )}
    </div>
  );
}

function ScenarioMenu({ sets, setSets, current, onLoad }: { sets: Record<string, Overrides>; setSets: (s: Record<string, Overrides>) => void; current: Overrides; onLoad: (o: Overrides) => void }) {
  const [name, setName] = useState("");
  return (
    <Popover trigger={(open, toggle) => <button className={`btn sec ${open ? "on" : ""}`} onClick={toggle}><Icon name="bookmark" className="sm" />Scenarios<Icon name="chevron-down" className="xs" /></button>}>
      {(close) => (
        <div style={{ width: 280 }}>
          <div className="label" style={{ padding: "6px 8px" }}>Save current changes as</div>
          <div className="row" style={{ padding: "0 8px 6px" }}>
            <input className="inp sm grow" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Higher rates" />
            <button className="btn xs" disabled={!name.trim() || !Object.keys(current).length} onClick={() => { setSets({ ...sets, [name.trim()]: current }); setName(""); }}>Save</button>
          </div>
          <hr />
          {Object.keys(sets).length === 0 && <div className="faint small" style={{ padding: "6px 8px" }}>No saved scenarios. They stay in this browser.</div>}
          {Object.entries(sets).map(([n, o]) => (
            <div key={n} className="row" style={{ padding: "0 4px" }}>
              <button className="grow" onClick={() => { onLoad(o); close(); }}><Icon name="bookmark" className="sm" />{n}<span className="faint xs" style={{ marginLeft: "auto" }}>{Object.keys(o).length}</span></button>
              <button className="ibtn sm" title="Delete" onClick={() => { const s = { ...sets }; delete s[n]; setSets(s); }}><Icon name="trash" className="xs" /></button>
            </div>
          ))}
        </div>
      )}
    </Popover>
  );
}

function ParamTree({ groups, overrides, effective, setOverrides }: { groups: ParamGroup[]; overrides: Overrides; effective: Overrides; setOverrides: (o: Overrides) => void }) {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<Set<string>>(() => new Set([groups[0]?.group].filter(Boolean) as string[]));
  const f = filter.trim().toLowerCase();
  useEffect(() => {
    const h = (e: Event) => {
      const path = (e as CustomEvent<string>).detail;
      const g = groups.find((x) => x.params.some((p) => p.path === path));
      if (g) setOpen((s) => new Set([...s, g.group]));
      window.setTimeout(() => { const el = document.getElementById(`p-${path}`); el?.scrollIntoView({ block: "center", behavior: "smooth" }); el?.animate([{ background: "#ad80d740" }, { background: "transparent" }], { duration: 1400 }); }, 60);
    };
    window.addEventListener("studio:focus", h);
    return () => window.removeEventListener("studio:focus", h);
  }, [groups]);
  return (
    <>
      <div style={{ padding: 8, borderBottom: "1px solid var(--line)" }}><div className="search"><Icon name="filter" /><input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter parameters" /></div></div>
      <div className="pane-b ptree">
        {groups.map((g) => {
          const ps = g.params.filter((p) => !f || `${p.label} ${p.path} ${g.group}`.toLowerCase().includes(f));
          if (!ps.length) return null;
          const isOpen = !!f || open.has(g.group);
          const mods = ps.filter((p) => p.path in effective).length;
          return (
            <div key={g.group}>
              <div className="g" onClick={() => { const s = new Set(open); if (s.has(g.group)) s.delete(g.group); else s.add(g.group); setOpen(s); }}>
                <Icon name={isOpen ? "chevron-down" : "chevron-right"} className="xs" />{g.group}
                {mods > 0 ? <span className="m">{mods}</span> : <span className="n">{ps.length}</span>}
              </div>
              {isOpen && ps.map((p) => <Param key={p.path} p={p} value={p.path in overrides ? overrides[p.path] : p.value} modified={p.path in effective}
                onChange={(v) => setOverrides({ ...overrides, [p.path]: v })} onReset={() => { const o = { ...overrides }; delete o[p.path]; setOverrides(o); }} />)}
            </div>
          );
        })}
      </div>
    </>
  );
}

function Param({ p, value, modified, onChange, onReset }: { p: ParamDef; value: number | boolean | null; modified: boolean; onChange: (v: number | boolean) => void; onReset: () => void }) {
  const scale = p.kind === "pct" ? 100 : 1;
  const [text, setText] = useState<string | null>(null);
  const n = typeof value === "number" ? value : null;
  const commitText = (s: string) => {
    const x = Number(s.replace("%", ""));
    if (Number.isFinite(x)) onChange(p.kind === "int" ? Math.round(x / scale) : Math.round((x / scale) * 1e6) / 1e6);
    setText(null);
  };
  return (
    <div className={`prow ${modified ? "mod" : ""}`} id={`p-${p.path}`} title={p.desc ?? p.path}>
      <span className="pl">{p.label}</span>
      {p.kind === "bool" ? <span style={{ justifySelf: "end" }}><Toggle checked={value === true} onChange={onChange} /></span> : (
        <input className="pv" value={text ?? show(p, n)} onFocus={() => setText(n == null ? "" : String(Math.round(n * scale * 1e4) / 1e4))}
          onChange={(e) => setText(e.target.value)} onBlur={(e) => commitText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setText(null); }} />
      )}
      {modified ? <button className="ibtn sm" title={`Reset to ${show(p, p.value)}`} onClick={onReset}><Icon name="discard" className="xs" /></button> : <span />}
      {p.kind !== "bool" && (
        <input type="range" className="sl ps" min={p.min} max={p.max} step={p.kind === "int" ? 1 : (p.max - p.min) / 200} value={n ?? p.min}
          onChange={(e) => { const v = Number(e.target.value); onChange(p.kind === "int" ? Math.round(v) : Math.round(v * 1e6) / 1e6); }} aria-label={p.label} />
      )}
      {modified && <span className="was">saved {show(p, p.value)}</span>}
      {p.default != null && !same(value, p.default) && (
        <button className="was dflt" onClick={() => onChange(p.default as number | boolean)} title="Set this constant back to its shipped default">
          <Icon name="history" className="xs" />default {show(p, p.default)}
        </button>
      )}
    </div>
  );
}

function CompanyCanvas({ company, list, onPick, overrides, byPath, setOverrides, right, setRight }: {
  company: string; list: { company: string; source: string }[]; onPick: (c: string) => void; overrides: Overrides; byPath: Record<string, ParamDef>; setOverrides: (o: Overrides) => void;
  right: boolean; setRight: (v: boolean) => void;
}) {
  const debounced = useDebounced(overrides, 200);
  const [sim, setSim] = useState<Simulation | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"sens" | "diff" | "inputs">("sens");
  const seq = useRef(0);
  useEffect(() => {
    if (!company) return;
    const n = ++seq.current;
    setBusy(true);
    api.post<Simulation>("/api/hybrid/simulate", { company, overrides: debounced, sensitivity: true })
      .then((s) => { if (n === seq.current) { setSim(s); setErr(null); } })
      .catch((e) => { if (n === seq.current) setErr(e); })
      .finally(() => { if (n === seq.current) setBusy(false); });
  }, [company, debounced]);
  const live = sim?.live, saved = sim?.saved;
  const delta = live && saved && isNum(live.value) && isNum(saved.value) && saved.value ? live.value / saved.value - 1 : null;
  const changed = Object.keys(overrides).length > 0;

  return (
    <>
      <section className="canvas">
        <div className="pane-h">
          <Select size="sm" value={company} onChange={onPick} style={{ maxWidth: 280 }} ariaLabel="Company" menuWidth={280}
            options={[...list.filter((c) => c.source === "research").map((c) => ({ value: c.company, label: shortName(c.company), text: c.company, group: "Research run (agent signals)" })),
              ...list.filter((c) => c.source === "report").map((c) => ({ value: c.company, label: shortName(c.company), text: c.company, group: "Valuation report (accounts only)" }))]} />
          {sim && <span className={`tag ${sim.source === "research" ? "hm" : ""}`}>{sim.source === "research" ? "agent signals" : "accounts only"} · FY{sim.fy}</span>}
          {busy && <Icon name="loading" className="spin faint sm" />}
          <span className="spacer" />
          {sim?.source === "research" && <Link to={companyPath(company)} className="btn xs ghost">Full analysis <Icon name="arrow-right" className="xs" /></Link>}
        </div>
        <div className="pane-b">
          {err != null && <div style={{ padding: 12 }}><ErrorNote error={err} /></div>}
          {!live ? <Loading rows={10} /> : (
            <>
              <div className="hero-v">
                <div><div className="k">HYBRID MODEL</div><div className="v hm">{money(live.value)}</div>
                  <div className={`d mono ${isNum(delta) && Math.abs(delta) > 0.0005 ? (delta > 0 ? "up" : "down") : "faint"}`}>{isNum(delta) && Math.abs(delta) > 0.0005 ? `${pct(delta, 1, true)} vs ${money(saved?.value, 0)}` : "= saved"}</div></div>
                <div><div className="k">Price</div><div className="v" style={{ color: "var(--price)" }}>{money(live.price)}</div><div className={`d mono ${isNum(live.upside) ? (live.upside >= 0 ? "up" : "down") : ""}`}>{pct(live.upside, 1, true)} upside</div></div>
                <div><div className="k">Range P10–P90</div><div className="v" style={{ fontSize: 17, marginTop: 6 }}>{money(live.low, 0)} – {money(live.high, 0)}</div><div className="d faint">buy-below {money(live.buy_below, 0)}</div></div>
                <div><div className="k">Label · confidence</div><div className="row" style={{ marginTop: 8 }}><LabelBadge label={live.label} /><span className="mono strong">{live.confidence.toFixed(0)}</span></div>
                  <div className="d faint">{saved && saved.label !== live.label ? <>was <span style={{ color: LABEL_HEX[saved.label] }}>{saved.label}</span></> : "unchanged"}</div></div>
              </div>
              <div className="cv-block"><h4>Valuation range<span className="spacer" /><RangeLegend ghost={changed} /></h4><ValueRange r={live} ghost={changed ? saved : null} /></div>
              <div className="cv-block"><h4>Bridge</h4><Bridge r={live} height={210} /></div>
              <div className="cv-block" style={{ padding: 0 }}><h4 style={{ padding: "18px 2px 0" }}>Lens contribution</h4><LensContribution r={live} /></div>
              {live.gate && live.gate.after < live.gate.before && <div style={{ padding: 14 }}><div className="note inf"><Icon name="filter" /><div>Growth gate active: growth was {pct(live.gate.pvgo_share, 0)} of the cash-flow lens (allowed {pct(live.gate.allowed, 0)}), cut from {money(live.gate.before, 0)} to {money(live.gate.after, 0)}.</div></div></div>}
            </>
          )}
        </div>
      </section>
      {!right ? (
        <button className="studio-tab r" onClick={() => setRight(true)} title="Show the inspector (])">
          <Icon name="chevron-left" className="xs" /><span>Sensitivity · Changes · Inputs</span>{changed && <b className="tag hm">{Object.keys(overrides).length}</b>}
        </button>
      ) : (
      <section className="insp-pane">
        <div className="pane-h" style={{ padding: 0 }}>
          <div className="tabs" style={{ border: 0, margin: 0, width: "100%" }}>
            {([["sens", "Sensitivity"], ["diff", `Changes${changed ? ` (${Object.keys(overrides).length})` : ""}`], ["inputs", "Inputs"]] as const).map(([k, l]) => (
              <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)} style={{ height: 39 }}>{l}</button>
            ))}
            <span className="spacer" />
            <button className="ibtn sm" onClick={() => setRight(false)} title="Hide the inspector (])" style={{ alignSelf: "center", marginRight: 6 }}><Icon name="chevron-right" className="xs" /></button>
          </div>
        </div>
        <div className="pane-b" style={{ padding: 14 }}>
          {tab === "sens" && (sim?.sensitivity?.length ? <Tornado rows={sim.sensitivity} byPath={byPath} /> : <span className="muted small">No sensitivity for this company.</span>)}
          {tab === "diff" && (changed ? (
            <div>
              {Object.entries(overrides).map(([k, v]) => (
                <div className="diff-row" key={k}>
                  <span className="strong ellipsis">{byPath[k]?.label ?? k}</span>
                  <button className="ibtn sm" title="Revert" onClick={() => { const o = { ...overrides }; delete o[k]; setOverrides(o); }}><Icon name="discard" className="xs" /></button>
                  <span className="mono xs"><span className="down">{show(byPath[k], byPath[k]?.value)}</span> → <span className="up">{show(byPath[k], v)}</span></span>
                </div>
              ))}
            </div>
          ) : <span className="muted small">No changes from the saved model.</span>)}
          {tab === "inputs" && sim && live && (
            <div className="kv">
              {([
                ["Cost of equity", pct(live.cost_of_equity, 2)], ["… CAPM part", pct(live.cost_of_equity_capm, 2)],
                ["Growth", pct(live.growth, 2)], ["Terminal growth", pct(live.growth_terminal, 2)],
                ["Quality ×", live.quality_multiplier.toFixed(3)], ["Haircut", pct(live.governance_haircut, 0)],
                ["σ", isNum(live.sigma) ? live.sigma.toFixed(3) : "—"],
                ["Type", titleCase(String(sim.inputs.regime ?? "—"))], ["Market cap", crore(sim.inputs.market_cap_cr)],
                ["FCFF (normalised)", crore(isNum(sim.inputs.fcff_norm) ? sim.inputs.fcff_norm / 1e7 : null)],
                ["NOPAT", crore(isNum(sim.inputs.nopat) ? sim.inputs.nopat / 1e7 : null)],
                ["ROE", pct(sim.inputs.roe_norm, 1)], ["Base growth", pct(sim.inputs.g_base, 1)],
                ["Beta (adjusted)", isNum(sim.inputs.beta_adj) ? sim.inputs.beta_adj.toFixed(2) : "—"],
                ["Debt / equity", isNum(sim.inputs.de_ratio) ? sim.inputs.de_ratio.toFixed(2) : "—"],
              ] as [string, string][]).map(([k, v]) => <Fragment key={k}><span className="k">{k}</span><span className="v">{v}</span></Fragment>)}
            </div>
          )}
        </div>
      </section>
      )}
    </>
  );
}

function Tornado({ rows, byPath }: { rows: NonNullable<Simulation["sensitivity"]>; byPath: Record<string, ParamDef> }) {
  const max = Math.max(0.005, ...rows.flatMap((r) => [Math.abs(r.down ?? 0), Math.abs(r.up ?? 0)]));
  return (
    <div>
      <div className="faint xs" style={{ marginBottom: 8 }}>Change in value for one step down (left) / up (right). Click to edit.</div>
      {rows.map((r) => {
        const p = byPath[r.path];
        const bar = (v: number | null, side: "l" | "r") => isNum(v) ? <span style={{ [side === "r" ? "left" : "right"]: "50%", width: `${(Math.abs(v) / max) * 50}%`, background: v >= 0 ? "var(--up)" : "var(--down)", opacity: side === "r" ? 0.9 : 0.55 } as React.CSSProperties} /> : null;
        return (
          <div key={r.path} className="trow" onClick={() => window.dispatchEvent(new CustomEvent("studio:focus", { detail: r.path }))} title={`${p?.label ?? r.path}: ${pct(r.down, 1, true)} / ${pct(r.up, 1, true)}`}>
            <span className="tl ellipsis">{p?.label ?? r.path}</span>
            <div className="tbar">{bar(r.down, "l")}{bar(r.up, "r")}</div>
            <span className="mono xs right">{pct(Math.max(Math.abs(r.down ?? 0), Math.abs(r.up ?? 0)), 1)}</span>
          </div>
        );
      })}
    </div>
  );
}

type PRow = PortfolioRow & { change: number | null };

function Portfolio({ overrides }: { overrides: Overrides }) {
  const debounced = useDebounced(overrides, 300);
  const q = useQuery({ queryKey: ["hm-portfolio", debounced], queryFn: () => api.post<PortfolioRow[]>("/api/hybrid/simulate-all", { overrides: debounced }), placeholderData: (p) => p });
  const rows: PRow[] = useMemo(() => (q.data ?? []).map((x) => ({ ...x, change: isNum(x.saved) && isNum(x.live) && x.saved ? x.live / x.saved - 1 : null })), [q.data]);
  const columns: Column<PRow>[] = [
    { key: "company", header: "Company", fixed: true, sticky: true, sort: (r) => r.company, render: (r) => <Link to={`/studio?company=${slug(r.company)}`} className="strong">{shortName(r.company)}</Link> },
    { key: "sector", header: "Sector", sort: (r) => r.sector, render: (r) => <span className="muted">{r.sector}</span> },
    { key: "price", header: "Price", align: "r", sort: (r) => r.price, render: (r) => <span className="mono">{money(r.price)}</span> },
    { key: "saved", header: "Saved value", align: "r", sort: (r) => r.saved, render: (r) => <span className="mono muted">{money(r.saved)}</span> },
    { key: "live", header: "Live value", align: "r", sort: (r) => r.live, render: (r) => <span className="mono hm">{money(r.live)}</span> },
    { key: "change", header: "Change", align: "r", sort: (r) => (isNum(r.change) ? Math.abs(r.change) : null), render: (r) => <span className={`mono ${isNum(r.change) && Math.abs(r.change) > 0.0005 ? (r.change > 0 ? "up" : "down") : "faint"}`}>{pct(r.change, 1, true)}</span> },
    { key: "label", header: "Label", render: (r) => r.saved_label !== r.live_label ? <span className="row"><LabelBadge label={r.saved_label} /><Icon name="arrow-right" className="xs faint" /><LabelBadge label={r.live_label} /></span> : <LabelBadge label={r.live_label} /> },
  ];
  const state = useGridState<PRow>("studio-portfolio", columns, { key: "change", asc: false });
  const ch = rows.map((r) => r.change).filter(isNum) as number[];
  const avg = ch.length ? ch.reduce((a, b) => a + b, 0) / ch.length : null;
  const moved = rows.filter((r) => r.saved_label !== r.live_label).length;
  return (
    <section className="portfolio-pane" style={{ gridColumn: "2 / -1" }}>
      <div className="band" style={{ borderRadius: 0, border: 0, borderBottom: "1px solid var(--line)" }}>
        <div><div className="k">Companies</div><div className="v">{rows.length}</div></div>
        <div><div className="k">Average change</div><div className={`v ${isNum(avg) ? (avg >= 0 ? "up" : "down") : ""}`}>{pct(avg, 1, true)}</div></div>
        <div><div className="k">Labels that move</div><div className="v">{moved}</div></div>
        <div><div className="k">Constants changed</div><div className="v hm">{Object.keys(overrides).length}</div></div>
      </div>
      {q.isError && <div style={{ padding: 12 }}><ErrorNote error={q.error} /></div>}
      <DataGrid rows={rows} columns={columns} rowKey={(r) => r.company} state={state} />
    </section>
  );
}

