import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AgentSettings, api, ModelTestResult, Provider, RunPrefs } from "../lib/api";
import { useKeys, useModels, usePrefs, useProviders, useSettings } from "../lib/hooks";
import { ago, titleCase } from "../lib/format";
import { AGENT_NAME } from "../lib/labels";
import { ErrorNote, Icon, Loading, PageHeader, Panel, QueryView, Toggle } from "../components/ui";
import { useApp } from "../components/workbenchContext";

const SECTIONS = [
  { id: "run", label: "Run settings", icon: "settings" },
  { id: "ai", label: "AI providers", icon: "sparkle" },
  { id: "agents", label: "Research agents", icon: "organization" },
  { id: "macro", label: "Macro inputs", icon: "globe" },
  { id: "yaml", label: "Settings file", icon: "file-code" },
];

export function Configuration() {
  const [params, setParams] = useSearchParams();
  const section = params.get("section") ?? "run";
  const cur = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0];
  return (
    <div className="page">
      <PageHeader crumbs={[{ label: "Operations" }, { label: "Configuration" }, { label: cur.label }]} title="Configuration"
        sub={<>HYBRID MODEL constants are tuned in the <Link to="/studio">Studio</Link>, where you can see their effect before committing.</>} />
      <div className="cfg">
        <nav className="cfg-nav">
          {SECTIONS.map((s) => <button key={s.id} className={section === s.id ? "on" : ""} onClick={() => setParams({ section: s.id })}><Icon name={s.icon} />{s.label}</button>)}
          <Link to="/studio" className="btn ghost sm" style={{ justifyContent: "flex-start", marginTop: 6 }}><Icon name="beaker" className="sm" />HYBRID MODEL Studio</Link>
        </nav>
        <div className="col" style={{ gap: 14, minWidth: 0 }}>
          {section === "run" && <RunSettings />}
          {section === "ai" && <AiProviders />}
          {section === "agents" && <YamlFields kind="agents" />}
          {section === "macro" && <YamlFields kind="macro" />}
          {section === "yaml" && <Raw />}
        </div>
      </div>
    </div>
  );
}

function Field({ label, desc, dirty, children }: { label: string; desc?: ReactNode; dirty?: boolean; children: ReactNode }) {
  return (
    <div className={`fbox ${dirty ? "dirty" : ""}`}>
      <div className="fl">{label}{dirty && <span className="dot busy" />}</div>
      {desc && <div className="fd">{desc}</div>}
      <div className="fc">{children}</div>
    </div>
  );
}
function Sel<T extends string>({ v, opts, on }: { v: T; opts: [T, string][]; on: (x: T) => void }) {
  return <select className="sel grow" value={v} onChange={(e) => on(e.target.value as T)}>{opts.map(([a, b]) => <option key={a} value={a}>{b}</option>)}</select>;
}
function Num({ v, on, min, max }: { v: number; on: (x: number) => void; min: number; max: number }) {
  return <input className="inp num" style={{ width: 110 }} type="number" min={min} max={max} value={v} onChange={(e) => on(Math.max(min, Math.min(max, Number(e.target.value) || min)))} />;
}

// ================================================================ run settings
function RunSettings() {
  const q = usePrefs();
  const models = useModels();
  const [p, setP] = useState<RunPrefs | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const qc = useQueryClient();
  const app = useApp();
  useEffect(() => { if (q.data && !p) setP(q.data.values); }, [q.data, p]);
  if (!p || !q.data) return <Loading rows={10} />;
  const saved = q.data.values;
  const d = (k: keyof RunPrefs) => JSON.stringify(p[k]) !== JSON.stringify(saved[k]);
  const dirty = (Object.keys(p) as (keyof RunPrefs)[]).filter(d).length;
  const set = <K extends keyof RunPrefs>(k: K, v: RunPrefs[K]) => setP({ ...p, [k]: v });
  const save = async () => {
    setSaving(true); setErr(null);
    try { const r = await api.put<{ values: RunPrefs }>("/api/run-preferences", p); setP(r.values); await qc.invalidateQueries({ queryKey: ["prefs"] }); app.toast("Run settings saved", "ok"); }
    catch (e) { setErr(e); } finally { setSaving(false); }
  };
  const reset = async () => { await fetch("/api/run-preferences", { method: "DELETE" }); await qc.invalidateQueries({ queryKey: ["prefs"] }); setP(q.data!.defaults); app.toast("Recommended defaults restored"); };
  const trad = (models.data ?? []).filter((m) => m.kind !== "ml");
  const ml = (models.data ?? []).filter((m) => m.kind === "ml");

  return (
    <>
      {err != null && <ErrorNote error={err} />}
      <Panel title="Data quality" meta="how strict the data gate is">
        <div className="fgrid">
          <Field label="Complete years required" dirty={d("min_complete_fy")} desc="Years that must carry every figure the models need."><Num v={p.min_complete_fy} min={1} max={30} on={(x) => set("min_complete_fy", x)} /></Field>
          <Field label="Years with a comparison price" dirty={d("min_benchmark_fy")} desc="Catches recent listings with nothing to score against."><Num v={p.min_benchmark_fy} min={0} max={30} on={(x) => set("min_benchmark_fy", x)} /></Field>
          <Field label="Companies that fail" dirty={d("screening")}><Sel v={p.screening} on={(x) => set("screening", x)} opts={[["enforce", "Leave them out"], ["report", "Flag, keep them"], ["off", "No check"]]} /></Field>
          <Field label="Rescue a run nobody passes" dirty={d("auto_relax")} desc="Lower the bar to the best achieved, with a warning."><Toggle checked={p.auto_relax} onChange={(x) => set("auto_relax", x)} /></Field>
          <Field label="Left-out companies in sector averages" dirty={d("keep_in_peers")}><Toggle checked={p.keep_in_peers} onChange={(x) => set("keep_in_peers", x)} /></Field>
          <Field label="Left-out companies in AI training" dirty={d("keep_in_ml")}><Toggle checked={p.keep_in_ml} onChange={(x) => set("keep_in_ml", x)} /></Field>
          <Field label="A year needs a share price" dirty={d("require_price")} desc="Stricter and more honest."><Toggle checked={p.require_price} onChange={(x) => set("require_price", x)} /></Field>
          <Field label="Audit every company" dirty={d("audit_all")} desc="List passing companies on the left-out sheets too."><Toggle checked={p.audit_all} onChange={(x) => set("audit_all", x)} /></Field>
        </div>
      </Panel>
      <Panel title="Prices" meta="what the answers are judged against">
        <div className="fgrid">
          <Field label="Comparison price" dirty={d("benchmark_basis")} desc="Changes every accuracy figure."><Sel v={p.benchmark_basis} on={(x) => set("benchmark_basis", x)} opts={[["may1", "1 May after year end"], ["mean", "Next year's average"], ["close", "Next year's close"]]} /></Field>
          <Field label="Days either side of 1 May" dirty={d("bench_offset_days")}><Num v={p.bench_offset_days} min={1} max={45} on={(x) => set("bench_offset_days", x)} /></Field>
          <Field label="Year's average price" dirty={d("mean_basis")} desc="Feeds the valuation itself."><Sel v={p.mean_basis} on={(x) => set("mean_basis", x)} opts={[["trading", "Trading days"], ["calendar", "Calendar days"]]} /></Field>
          <Field label="Exchange" dirty={d("exchange")}><Sel v={p.exchange} on={(x) => set("exchange", x)} opts={[[".NS", "NSE"], [".BO", "BSE"]]} /></Field>
        </div>
      </Panel>
      <Panel title="Models" meta="a model switched off is not computed and loses its columns">
        <div className="fgrid">
          {[...trad, ...ml].map((m) => (
            <Field key={m.key} label={m.name} dirty={p.models[m.key] !== saved.models[m.key]} desc={m.blurb.split(". ")[0] + "."}>
              <Toggle checked={!!p.models[m.key]} onChange={(x) => set("models", { ...p.models, [m.key]: x })} label={m.kind === "ml" ? "AI" : m.kind === "hybrid" ? "Blend" : "Accounts"} />
            </Field>
          ))}
          <Field label="AI stage" dirty={d("ml_enabled")} desc="Master switch for the four learners."><Toggle checked={p.ml_enabled} onChange={(x) => set("ml_enabled", x)} /></Field>
          <Field label="How the AI models are tested" dirty={d("ml_split")}><Sel v={p.ml_split} on={(x) => set("ml_split", x)} opts={[["hybrid", "Hybrid split (recommended)"], ["expanding", "Earlier years only"], ["loyo", "All other years (leaks)"]]} /></Field>
          <Field label="Fill gaps in the accounts" dirty={d("estimation")} desc="Every estimate is starred and explained."><Sel v={p.estimation} on={(x) => set("estimation", x)} opts={[["balanced", "Balanced (recommended)"], ["aggressive", "As much as possible"], ["off", "Published only"]]} /></Field>
        </div>
      </Panel>
      <Panel title="Report & files">
        <div className="fgrid">
          <Field label="Draw the charts" dirty={d("analyze")}><Toggle checked={p.analyze} onChange={(x) => set("analyze", x)} /></Field>
          <Field label="Chart DPI" dirty={d("dpi")}><Num v={p.dpi} min={72} max={600} on={(x) => set("dpi", x)} /></Field>
          <Field label="Year labels" dirty={d("fy_labels")}><Sel v={p.fy_labels} on={(x) => set("fy_labels", x)} opts={[["range", "2023-24"], ["int", "2024"]]} /></Field>
          <Field label="Empty cells" dirty={d("reasons")}><Sel v={p.reasons} on={(x) => set("reasons", x)} opts={[["code", "Short code"], ["detailed", "Full sentence"], ["off", "Blank"]]} /></Field>
          <Field label="Use hand-entered figures" dirty={d("overrides")} desc="data/fundamentals_override.csv"><Toggle checked={p.overrides} onChange={(x) => set("overrides", x)} /></Field>
          <Field label="Default years (FY)" dirty={d("start_year") || d("end_year")}><Num v={p.start_year} min={2000} max={2100} on={(x) => set("start_year", x)} /><span className="faint">to</span><Num v={p.end_year} min={2000} max={2100} on={(x) => set("end_year", x)} /></Field>
        </div>
      </Panel>
      <div className="row"><button className="btn ghost sm" onClick={reset}><Icon name="history" className="sm" />Restore recommended defaults</button></div>
      {dirty > 0 && (
        <div className="savebar">
          <Icon name="edit" className="info" /><span>{dirty} unsaved setting{dirty === 1 ? "" : "s"}</span><span className="spacer" />
          <button className="btn sec sm" onClick={() => setP(saved)}>Discard</button>
          <button className="btn sm" onClick={save} disabled={saving}><Icon name={saving ? "loading" : "save"} className={`sm ${saving ? "spin" : ""}`} />Save</button>
        </div>
      )}
    </>
  );
}

// ================================================================ AI providers
const INFO: Record<string, { label: string; url: string }> = {
  groq: { label: "Groq", url: "https://console.groq.com/keys" },
  gemini: { label: "Google Gemini", url: "https://aistudio.google.com/apikey" },
  nvidia: { label: "NVIDIA NIM", url: "https://build.nvidia.com" },
};

function AiProviders() {
  const q = useProviders();
  const keys = useKeys();
  const qc = useQueryClient();
  const refresh = () => { qc.invalidateQueries({ queryKey: ["providers"] }); keys.refetch(); qc.invalidateQueries({ queryKey: ["status"] }); };
  return (
    <>
      <div className="note inf"><Icon name="shield" /><div>Keys are stored in this project's <span className="mono">.env</span> (git-ignored) and never sent back to the page. Providers retire models often — choose from each provider's <b>live</b> list and press <b>Test</b>.</div></div>
      <QueryView q={q}>
        {(d) => (
          <>
            <Panel title="Providers" meta="fast = bulk reading · smart = reasoning and writing" flush>
              <table className="dg">
                <thead><tr><th>Provider</th><th>Key</th><th>Fast model</th><th>Smart model</th><th className="r">Limits / min · day</th></tr></thead>
                <tbody>{d.providers.map((p) => <ProviderRow key={p.name} p={p} onChanged={refresh} />)}</tbody>
              </table>
            </Panel>
            <Routes routes={d.routes} providers={d.providers} />
          </>
        )}
      </QueryView>
      <YamlFields kind="llm" />
    </>
  );
}

function ProviderRow({ p, onChanged }: { p: Provider; onChanged: () => void }) {
  const info = INFO[p.name] ?? { label: titleCase(p.name), url: "" };
  const [key, setKey] = useState("");
  const [edit, setEdit] = useState(!p.has_key);
  const app = useApp();
  const [n, setN] = useState(0);
  const models = useQuery({ queryKey: ["llm-models", p.name, p.has_key, n], queryFn: () => api.get<{ id: string; chat: boolean }[]>(`/api/llm/models?provider=${p.name}${n ? "&refresh=true" : ""}`), enabled: p.has_key, retry: 0 });
  const saveKey = async (v: string) => {
    try { await api.put("/api/settings/keys", { values: { [p.key_env]: v } }); setKey(""); setEdit(!v); onChanged(); app.toast(v ? `${info.label} key saved` : `${info.label} key removed`, "ok"); }
    catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); }
  };
  return (
    <tr style={{ verticalAlign: "top" }}>
      <td style={{ paddingTop: 12 }}>
        <div className="row"><span className={`dot ${p.has_key ? "ok" : ""}`} /><b className="strong">{info.label}</b></div>
        <div className="xs faint mono" style={{ marginTop: 2 }}>{p.key_env}</div>
        {info.url && <a href={info.url} target="_blank" rel="noreferrer noopener" className="xs">Get a key</a>}
      </td>
      <td style={{ paddingTop: 10, width: 260 }}>
        {edit ? (
          <div className="row"><input className="inp sm mono grow" type="password" autoComplete="off" placeholder="paste API key" value={key} onChange={(e) => setKey(e.target.value)} /><button className="btn xs" disabled={!key.trim()} onClick={() => saveKey(key.trim())}>Save</button>{p.has_key && <button className="ibtn sm" onClick={() => setEdit(false)}><Icon name="close" className="xs" /></button>}</div>
        ) : (
          <div className="row"><span className="tag up">saved</span><button className="btn xs ghost" onClick={() => setEdit(true)}>Replace</button><button className="btn xs ghost" onClick={() => saveKey("")}>Remove</button></div>
        )}
        {p.has_key && <div className="row xs faint" style={{ marginTop: 6 }}>{models.data ? `${models.data.filter((m) => m.chat).length} chat models` : models.isLoading ? "loading models…" : ""}<button className="btn xs ghost" onClick={() => setN((x) => x + 1)}><Icon name="refresh" className="xs" /></button></div>}
        {models.isError && <div style={{ marginTop: 6 }}><ErrorNote error={models.error} /></div>}
      </td>
      {(["fast", "smart"] as const).map((tier) => (
        <td key={tier} style={{ paddingTop: 10, whiteSpace: "normal", minWidth: 240 }}>
          {p.has_key ? <ModelPick provider={p.name} tier={tier} current={p.models[tier] ?? ""} models={models.data ?? []} loading={models.isLoading} onSaved={onChanged} /> : <span className="faint xs">add a key first</span>}
        </td>
      ))}
      <td className="r mono xs faint" style={{ paddingTop: 12 }}>{p.limits.requests_per_minute ?? "—"} · {p.limits.requests_per_day ?? "—"}</td>
    </tr>
  );
}

function ModelPick({ provider, tier, current, models, loading, onSaved }: { provider: string; tier: string; current: string; models: { id: string; chat: boolean }[]; loading: boolean; onSaved: () => void }) {
  const [v, setV] = useState(current);
  const [res, setRes] = useState<ModelTestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const app = useApp();
  useEffect(() => setV(current), [current]);
  const known = models.some((m) => m.id === current);
  const test = async () => {
    setBusy(true); setRes(null);
    try { setRes(await api.post<ModelTestResult>("/api/llm/test", { provider, model: v })); }
    catch (e) { setRes({ ok: false, status: null, seconds: 0, error: e instanceof Error ? e.message : String(e) }); } finally { setBusy(false); }
  };
  const use = async () => {
    try { await api.patch("/api/settings/agents", { values: { [`llm.providers.${provider}.models.${tier}`]: v } }); onSaved(); app.toast(`${provider} ${tier} → ${v}`, "ok"); }
    catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); }
  };
  return (
    <div className="col" style={{ gap: 6 }}>
      <select className="sel sm" value={v} disabled={loading} onChange={(e) => { setV(e.target.value); setRes(null); }}>
        {!known && current && <option value={current}>{current} (not offered)</option>}
        {models.filter((m) => m.chat).map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
        <optgroup label="Probably not chat models">{models.filter((m) => !m.chat).map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}</optgroup>
      </select>
      <div className="row" style={{ gap: 4 }}>
        <button className="btn xs sec" onClick={test} disabled={!v || busy}><Icon name={busy ? "loading" : "beaker"} className={`xs ${busy ? "spin" : ""}`} />Test</button>
        <button className="btn xs" onClick={use} disabled={!v || v === current}>Use</button>
        {res && <span className={`xs ${res.ok ? "up" : "down"} ellipsis`} title={res.error ?? ""}>{res.ok ? `✓ ${res.seconds}s` : `✗ ${res.status ? `HTTP ${res.status}` : "failed"}`}</span>}
      </div>
      {res && !res.ok && <span className="xs down" style={{ lineHeight: 1.4 }}>{res.error}</span>}
      {!known && current && !loading && models.length > 0 && !res && <span className="xs warn">Saved model not in this key's list — probably retired.</span>}
    </div>
  );
}

function Routes({ routes, providers }: { routes: Record<string, string[]>; providers: Provider[] }) {
  const [r, setR] = useState(routes);
  const qc = useQueryClient();
  const app = useApp();
  useEffect(() => setR(routes), [routes]);
  const move = (tier: string, i: number, dlt: number) => { const l = [...(r[tier] ?? [])]; const j = i + dlt; if (j < 0 || j >= l.length) return; [l[i], l[j]] = [l[j], l[i]]; setR({ ...r, [tier]: l }); };
  const dirty = JSON.stringify(r) !== JSON.stringify(routes);
  const save = async () => { try { await api.put("/api/llm/routes", r); qc.invalidateQueries({ queryKey: ["providers"] }); app.toast("Routing order saved", "ok"); } catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); } };
  const has = (s: string) => providers.find((p) => p.name === s.split(":")[0])?.has_key;
  return (
    <Panel title="Fail-over order" meta="first provider with a key answers; on a limit or error the next takes over" tools={<button className="btn xs" disabled={!dirty} onClick={save}>Save order</button>}>
      <div className="grid c2">
        {(["fast", "smart"] as const).map((tier) => (
          <div key={tier}>
            <div className="label" style={{ marginBottom: 6 }}>{tier}</div>
            {(r[tier] ?? []).map((s, i) => (
              <div key={s} className="row" style={{ padding: "5px 0", borderTop: i ? "1px solid var(--line-soft)" : undefined }}>
                <span className="mono faint" style={{ width: 16 }}>{i + 1}</span><span className={`dot ${has(s) ? "ok" : ""}`} /><span className="grow">{titleCase(s.split(":")[0])}</span>
                <button className="ibtn sm" onClick={() => move(tier, i, -1)} disabled={i === 0}><Icon name="arrow-up" className="xs" /></button>
                <button className="ibtn sm" onClick={() => move(tier, i, 1)} disabled={i === (r[tier]?.length ?? 0) - 1}><Icon name="arrow-down" className="xs" /></button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ================================================================ YAML-backed fields
type K = "pct" | "num" | "int" | "bool";
interface F { path: string; label: string; kind: K; desc?: string }
interface G { title: string; meta?: string; fields: F[] }
const get = (o: unknown, path: string): unknown => path.split(".").reduce<unknown>((x, k) => (x && typeof x === "object" ? (x as Record<string, unknown>)[k] : undefined), o);

function groupsFor(kind: string, data: Record<string, unknown>): G[] {
  if (kind === "macro") return [
    { title: "Hand-set macro inputs", meta: "update when RBI policy, CPI or GDP change", fields: [
      { path: "macro.repo_rate", label: "RBI repo rate", kind: "pct" }, { path: "macro.cpi_inflation", label: "CPI inflation", kind: "pct" },
      { path: "macro.rbi_inflation_target", label: "RBI inflation target", kind: "pct" }, { path: "macro.real_gdp_growth", label: "Real GDP growth", kind: "pct" },
      { path: "macro.india_10y_yield", label: "India 10Y yield", kind: "pct" }] },
    { title: "Normal levels", meta: "live readings are compared with these", fields: [
      { path: "macro.normal_india_vix", label: "Normal India VIX", kind: "num" }, { path: "macro.normal_brent_usd", label: "Normal Brent (USD)", kind: "num" },
      { path: "macro.inr_depreciation_tolerance_1y", label: "Tolerated INR fall / year", kind: "pct" }] },
  ];
  if (kind === "llm") return [{ title: "AI usage limits", fields: [
    { path: "llm.enabled", label: "Use AI when keys are present", kind: "bool" }, { path: "llm.max_calls_per_run", label: "Max AI calls per run", kind: "int" },
    { path: "llm.cache_hours", label: "Reuse identical answers (hours)", kind: "int" }, { path: "llm.retries", label: "Retries per provider", kind: "int" },
    { path: "llm.timeout_seconds", label: "Timeout (seconds)", kind: "int" }, { path: "llm.temperature", label: "Temperature", kind: "num" }] }];
  const agents = (data.agents ?? {}) as Record<string, Record<string, unknown>>;
  const out: G[] = Object.entries(agents).filter(([l, m]) => l !== "validation" && m && typeof m === "object").map(([lead, m]) => ({
    title: lead === "chief" ? "Chief — weight of each lead" : titleCase(lead), meta: lead === "chief" ? "share of the overall research score" : "analyst weight · 0 switches off",
    fields: Object.keys(m).map((a) => ({ path: `agents.${lead}.${a}`, label: lead === "chief" ? titleCase(a) : AGENT_NAME[a] ?? titleCase(a), kind: "num" as K })),
  }));
  out.push({ title: "Evidence rules", meta: "enforced before anything reaches the HYBRID MODEL", fields: [
    { path: "agents.validation.max_evidence_age_days", label: "Oldest financial evidence (days)", kind: "int" }, { path: "agents.validation.max_news_age_days", label: "Oldest news (days)", kind: "int" },
    { path: "agents.validation.min_sources_for_claim", label: "Sources per finding", kind: "int" }, { path: "agents.validation.require_source_url", label: "News & filings need a link", kind: "bool" }] });
  out.push({ title: "Research runs", fields: [
    { path: "run.parallel_companies", label: "Companies at once", kind: "int", desc: "Keep low on free AI tiers" }, { path: "run.history_years", label: "Years of history", kind: "int" },
    { path: "run.base_valuation_ml", label: "Train AI models in research", kind: "bool", desc: "Slow" }, { path: "run.news_lookback_days", label: "News look-back (days)", kind: "int" },
    { path: "run.ownership_lookback_days", label: "Ownership look-back (days)", kind: "int" }, { path: "run.feed_cache_hours", label: "Reuse downloads (hours)", kind: "int" },
    { path: "run.keep_reports", label: "Reports kept", kind: "int" }, { path: "alerts.telegram", label: "Telegram alerts", kind: "bool", desc: "needs bot token + chat id in .env" }] });
  return out;
}

const toT = (k: K, v: unknown) => (v == null ? "" : k === "pct" && typeof v === "number" ? String(Math.round(v * 1e6) / 1e4) : String(v));
const fromT = (k: K, s: string): number | boolean | null => { if (k === "bool") return s === "true"; const n = Number(s); if (!s.trim() || !Number.isFinite(n)) return null; return k === "int" ? Math.round(n) : k === "pct" ? Math.round(n * 1e4) / 1e6 : n; };

function YamlFields({ kind }: { kind: string }) {
  const q = useSettings();
  return <QueryView q={q}>{(s) => s.error ? <ErrorNote error={`agent_settings.yaml does not parse: ${s.error}`} /> : <Fields key={kind} s={s} groups={groupsFor(kind, s.data)} />}</QueryView>;
}

function Fields({ s, groups }: { s: AgentSettings; groups: G[] }) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const qc = useQueryClient();
  const app = useApp();
  const all = useMemo(() => groups.flatMap((g) => g.fields), [groups]);
  const dirty = Object.keys(edits).filter((p) => { const f = all.find((x) => x.path === p); return f && edits[p] !== toT(f.kind, get(s.data, p)); });
  const bad = dirty.filter((p) => fromT(all.find((x) => x.path === p)!.kind, edits[p]) === null);
  const save = async () => {
    setSaving(true);
    try {
      const values = Object.fromEntries(dirty.map((p) => [p, fromT(all.find((x) => x.path === p)!.kind, edits[p])]));
      qc.setQueryData(["settings"], await api.patch<AgentSettings>("/api/settings/agents", { values }));
      setEdits({}); app.toast(`Saved ${dirty.length} setting(s)`, "ok");
    } catch (e) { app.toast(e instanceof Error ? e.message : String(e), "error"); } finally { setSaving(false); }
  };
  return (
    <>
      {groups.map((g) => (
        <Panel key={g.title} title={g.title} meta={g.meta}>
          <div className="fgrid">
            {g.fields.map((f) => {
              const cur = get(s.data, f.path);
              const val = edits[f.path] ?? toT(f.kind, cur);
              const isD = dirty.includes(f.path);
              const set = (v: string) => setEdits((e) => ({ ...e, [f.path]: v }));
              return (
                <Field key={f.path} label={f.label} dirty={isD} desc={cur === undefined ? "Not in the file — default used" : f.desc}>
                  {f.kind === "bool" ? <Toggle checked={val === "true"} disabled={cur === undefined} onChange={(v) => set(String(v))} /> : (
                    <><input className={`inp num ${isD && fromT(f.kind, val) === null ? "bad" : ""}`} style={{ width: 110 }} disabled={cur === undefined} value={val} onChange={(e) => set(e.target.value)} />{f.kind === "pct" && <span className="faint">%</span>}</>
                  )}
                </Field>
              );
            })}
          </div>
        </Panel>
      ))}
      {dirty.length > 0 && (
        <div className="savebar">
          <Icon name="edit" className="info" /><span>{dirty.length} unsaved</span><span className="spacer" />
          <button className="btn sec sm" onClick={() => setEdits({})}>Discard</button>
          <button className="btn sm" disabled={bad.length > 0 || saving} onClick={save}><Icon name="save" className="sm" />Save</button>
        </div>
      )}
    </>
  );
}

function Raw() {
  const q = useSettings();
  return <QueryView q={q}>{(s) => <RawEditor s={s} />}</QueryView>;
}
function RawEditor({ s }: { s: AgentSettings }) {
  const [text, setText] = useState(s.text);
  const [err, setErr] = useState<unknown>(null);
  const qc = useQueryClient();
  const app = useApp();
  const g = useRef<HTMLDivElement>(null);
  useEffect(() => setText(s.text), [s.text]);
  const dirty = text !== s.text;
  const save = async () => {
    setErr(null);
    try { qc.setQueryData(["settings"], await api.put<AgentSettings>("/api/settings/agents", { text })); app.toast("Saved — previous version kept as agent_settings.yaml.bak", "ok"); } catch (e) { setErr(e); }
  };
  return (
    <Panel title="agent_settings.yaml" meta={`saved ${ago(s.updated)} · validated before writing`} tools={<><button className="btn xs sec" disabled={!dirty} onClick={() => setText(s.text)}>Revert</button><button className="btn xs" disabled={!dirty} onClick={save}><Icon name="save" className="xs" />Save</button></>}>
      {err != null && <div style={{ marginBottom: 10 }}><ErrorNote error={err} /></div>}
      <div className="yaml">
        <div className="yaml-g" ref={g}>{Array.from({ length: text.split("\n").length }, (_, i) => <div key={i}>{i + 1}</div>)}</div>
        <textarea className="yaml-t" spellCheck={false} value={text} onChange={(e) => setText(e.target.value)}
          onScroll={(e) => { if (g.current) g.current.scrollTop = e.currentTarget.scrollTop; }}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); if (dirty) save(); }
            else if (e.key === "Tab") { e.preventDefault(); const t = e.currentTarget, a = t.selectionStart; setText(text.slice(0, a) + "  " + text.slice(t.selectionEnd)); requestAnimationFrame(() => t.setSelectionRange(a + 2, a + 2)); }
          }} />
      </div>
    </Panel>
  );
}
