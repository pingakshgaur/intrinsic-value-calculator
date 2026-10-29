import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, LlmAuth, LlmStyle, ModelTestResult, Provider, ProviderPreset, ProvidersInfo } from "../lib/api";
import { useProviders } from "../lib/hooks";
import { Drawer, ErrorNote, Icon, Panel, QueryView, Toggle } from "./ui";
import { useApp } from "./workbenchContext";
import { ActionMenu, Select } from "./Select";

const STYLE_TEXT: Record<LlmStyle, string> = { openai: "OpenAI-compatible", anthropic: "Anthropic Messages API" };
const AUTH_TEXT: Record<LlmAuth, string> = { bearer: "Authorization: Bearer <key>", "x-api-key": "x-api-key header", "api-key": "api-key header (Azure)", none: "No key (local server)" };

const err = (e: unknown) => (e instanceof Error ? e.message : String(e));
// Ollama has its own Configuration section, Local AI (OllamaPanel)
const cloud = (d: ProvidersInfo) => d.providers.filter((p) => p.name !== "ollama");

/** Every AI provider: add any service, several keys each, models, limits, the fail-over order. */
export function AiProviders() {
  const q = useProviders();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["providers"] }); qc.invalidateQueries({ queryKey: ["status"] }); qc.invalidateQueries({ queryKey: ["keys"] }); };
  return (
    <>
      <div className="note inf"><Icon name="shield" /><div>Keys are stored in this project's <span className="mono">.env</span> (git-ignored) and never sent back to the page. Add as many providers and keys as you like: when a key hits its limit or is rejected, the next key - then the next provider - takes over. Providers retire models often, so pick from each provider's <b>live</b> list and press <b>Test</b>.</div></div>
      <QueryView q={q}>
        {(d) => (
          <>
            <Panel title="Providers" meta={`${cloud(d).filter((p) => p.enabled && p.has_key).length} ready of ${cloud(d).length} · fast = bulk reading · smart = reasoning and writing`} flush
              tools={<button className="btn xs" onClick={() => setAdding(true)}><Icon name="add" className="xs" />Add provider</button>}>
              <div className="provs">{cloud(d).map((p) => <ProviderCard key={p.name} p={p} onChanged={refresh} onEdit={() => setEditing(p)} />)}</div>
              {!cloud(d).length && <div className="empty" style={{ padding: 24 }}><span className="small">No providers yet. Add one to let the agents read and write with AI.</span></div>}
            </Panel>
            <Link to="/configuration?section=local" className="note inf" style={{ textDecoration: "none" }}><Icon name="vm" /><div><b>Local models (Ollama)</b> — free AI on this computer, no key or daily limit — have their own section: <u>Configuration → Local AI (Ollama)</u>.</div></Link>
            <Routes info={d} />
            {adding && <AddProvider info={d} onClose={() => setAdding(false)} onDone={refresh} />}
            {editing && <EditProvider p={editing} info={d} onClose={() => setEditing(null)} onDone={refresh} />}
          </>
        )}
      </QueryView>
    </>
  );
}

function ProviderCard({ p, onChanged, onEdit }: { p: Provider; onChanged: () => void; onEdit: () => void }) {
  const app = useApp();
  const [key, setKey] = useState("");
  const [n, setN] = useState(0);
  const ready = p.has_key;
  const models = useQuery({
    queryKey: ["llm-models", p.name, p.keys.map((k) => k.env).join(","), n],
    queryFn: () => api.get<{ id: string; chat: boolean }[]>(`/api/llm/models?provider=${encodeURIComponent(p.name)}${n ? "&refresh=true" : ""}`),
    enabled: ready && p.enabled, retry: 0, staleTime: 600_000,
  });
  const call = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); onChanged(); app.toast(ok, "ok"); } catch (e) { app.toast(err(e), "error"); } };
  const addKey = () => call(async () => { await api.post(`/api/llm/providers/${p.name}/keys`, { value: key.trim() }); setKey(""); }, `Key added to ${p.label}`);
  return (
    <section className={`prov ${p.enabled ? "" : "off"}`}>
      <div className="prov-id">
        <div className="row"><span className={`dot ${p.enabled && ready ? "ok" : ""}`} /><b className="strong ellipsis">{p.label}</b>
          <span className="spacer" />
          <button className="ibtn sm" onClick={onEdit} title="Edit this provider"><Icon name="edit" className="xs" /></button></div>
        <div className="xs faint">{STYLE_TEXT[p.style]}{p.source !== "settings" ? " · added here" : ""}</div>
        <div className="xs faint mono ellipsis" title={p.base_url}>{p.base_url.replace(/^https?:\/\//, "")}</div>
        <div className="xs faint">Limits <span className="mono">{p.limits.requests_per_minute}/min · {p.limits.requests_per_day}/day per key</span></div>
        <div className="row" style={{ marginTop: 4, gap: 10 }}>
          <Toggle checked={p.enabled} onChange={(v) => call(() => api.put(`/api/llm/providers/${p.name}`, { enabled: v }), v ? `${p.label} switched on` : `${p.label} switched off`)} label={p.enabled ? "On" : "Off"} />
          {p.preset && <a href={p.preset} target="_blank" rel="noreferrer noopener" className="xs">Get a key</a>}
        </div>
      </div>
      <div>
        <div className="label prov-l">API keys {p.auth !== "none" && <span className="faint">· tried in this order</span>}</div>
        {p.auth === "none" ? <span className="xs faint">No key needed - a server on this computer.</span> : (
          <>
            <div className="prov-keys">
              {p.keys.filter((k) => k.set).map((k, i) => <KeyRow key={k.env} p={p} k={k} first={i === 0} model={p.models.fast || p.models.smart || ""} onChanged={onChanged} />)}
              {!p.keys.some((k) => k.set) && <span className="xs faint">No key yet.</span>}
            </div>
            <div className="row" style={{ marginTop: 6 }}>
              <input className="inp sm mono grow" type="password" autoComplete="off" placeholder={p.keys.some((k) => k.set) ? "add another key" : "paste API key"} value={key}
                onChange={(e) => setKey(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && key.trim()) addKey(); }} />
              <button className="btn xs" disabled={!key.trim()} onClick={addKey}><Icon name="add" className="xs" />Add</button>
            </div>
          </>
        )}
        {ready && p.enabled && <div className="row xs faint" style={{ marginTop: 6 }}>{models.data ? `${models.data.filter((m) => m.chat).length} chat models` : models.isLoading ? "loading models…" : ""}
          <button className="btn xs ghost" onClick={() => setN((x) => x + 1)} title="Reload the model list"><Icon name="refresh" className="xs" /></button></div>}
        {models.isError && <div style={{ marginTop: 6 }}><ErrorNote error={models.error} /></div>}
      </div>
      {(["fast", "smart"] as const).map((tier) => (
        <div key={tier}>
          <div className="label prov-l">{tier === "fast" ? "Fast model" : "Smart model"}</div>
          {ready ? <ModelPick p={p} tier={tier} current={p.models[tier] ?? ""} models={models.data ?? []} loading={models.isLoading} onSaved={onChanged} /> : <span className="faint xs">add a key first</span>}
        </div>
      ))}
    </section>
  );
}

function KeyRow({ p, k, first, model, onChanged }: { p: Provider; k: { env: string; masked: string }; first: boolean; model: string; onChanged: () => void }) {
  const app = useApp();
  const [res, setRes] = useState<ModelTestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const test = async () => {
    setBusy(true); setRes(null);
    try { setRes(await api.post<ModelTestResult>("/api/llm/test", { provider: p.name, model, key: k.env })); }
    catch (e) { setRes({ ok: false, status: null, seconds: 0, error: err(e) }); } finally { setBusy(false); }
  };
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); onChanged(); app.toast(ok, "ok"); } catch (e) { app.toast(err(e), "error"); } };
  return (
    <div className="prov-key">
      <span className="mono">{k.masked || "••••"}</span>
      <span className="xs faint mono ellipsis" title={k.env}>{k.env}</span>
      {first && <span className="tag xs">first</span>}
      <span className="spacer" />
      {res && <span className={`xs ${res.ok ? "up" : "down"}`} title={res.error ?? res.reply ?? ""}>{res.ok ? `✓ ${res.seconds}s` : `✗ ${res.status ? `HTTP ${res.status}` : "failed"}`}</span>}
      <button className="ibtn sm" onClick={test} disabled={!model || busy} title={model ? `Test this key with ${model}` : "Choose a model first"}><Icon name={busy ? "loading" : "beaker"} className={`xs ${busy ? "spin" : ""}`} /></button>
      {!first && <button className="ibtn sm" onClick={() => act(() => api.post(`/api/llm/providers/${p.name}/keys/${k.env}/first`), `${k.env} is tried first now`)} title="Try this key first"><Icon name="arrow-up" className="xs" /></button>}
      <button className="ibtn sm" onClick={() => { if (confirm(`Remove the key in ${k.env}?`)) act(() => api.del(`/api/llm/providers/${p.name}/keys/${k.env}`), "Key removed"); }} title="Remove this key"><Icon name="trash" className="xs" /></button>
    </div>
  );
}

function ModelPick({ p, tier, current, models, loading, onSaved }: { p: Provider; tier: "fast" | "smart"; current: string; models: { id: string; chat: boolean }[]; loading: boolean; onSaved: () => void }) {
  const [v, setV] = useState(current);
  const [typed, setTyped] = useState(false);
  const [res, setRes] = useState<ModelTestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const app = useApp();
  useEffect(() => setV(current), [current]);
  const known = models.some((m) => m.id === current);
  const test = async () => {
    setBusy(true); setRes(null);
    try { setRes(await api.post<ModelTestResult>("/api/llm/test", { provider: p.name, model: v })); }
    catch (e) { setRes({ ok: false, status: null, seconds: 0, error: err(e) }); } finally { setBusy(false); }
  };
  const use = async () => {
    try { await api.put(`/api/llm/providers/${p.name}`, { models: { ...p.models, [tier]: v } }); onSaved(); app.toast(`${p.label} ${tier} → ${v}`, "ok"); }
    catch (e) { app.toast(err(e), "error"); }
  };
  return (
    <div className="col" style={{ gap: 6 }}>
      {typed || (!loading && !models.length) ? (
        <input className="inp sm mono" value={v} placeholder="model id" onChange={(e) => { setV(e.target.value.trim()); setRes(null); }} />
      ) : (
        <Select size="sm" style={{ width: "100%" }} title={v} value={v || null} disabled={loading} placeholder="Choose a model…" menuWidth={320} onChange={(x) => { setV(x); setRes(null); }}
          options={[
            ...(!known && current ? [{ value: current, label: current, hint: "not offered" }] : []),
            ...models.filter((m) => m.chat).map((m) => ({ value: m.id, label: m.id })),
            ...models.filter((m) => !m.chat).map((m) => ({ value: m.id, label: m.id, group: "Probably not chat models" })),
          ]} />
      )}
      <div className="row" style={{ gap: 4 }}>
        <button className="btn xs sec" onClick={test} disabled={!v || busy}><Icon name={busy ? "loading" : "beaker"} className={`xs ${busy ? "spin" : ""}`} />Test</button>
        <button className="btn xs" onClick={use} disabled={!v || v === current}>Use</button>
        {models.length > 0 && <button className="btn xs ghost" onClick={() => setTyped(!typed)} title={typed ? "Pick from the list" : "Type a model id"}><Icon name={typed ? "list-flat" : "edit"} className="xs" /></button>}
        {res && <span className={`xs ${res.ok ? "up" : "down"} ellipsis`} title={res.error ?? ""}>{res.ok ? `✓ ${res.seconds}s` : `✗ ${res.status ? `HTTP ${res.status}` : "failed"}`}</span>}
      </div>
      {res && !res.ok && <span className="xs down" style={{ lineHeight: 1.4, overflowWrap: "anywhere" }}>{res.error}</span>}
      {!known && current && !loading && models.length > 0 && !res && <span className="xs warn">Saved model not in this key's list - probably retired.</span>}
    </div>
  );
}

/** The provider's connection settings, in a drawer. */
function ProviderForm({ value, onChange, info, isNew }: { value: Partial<Provider> & { name: string; rpm?: number; rpd?: number; tpm?: number }; onChange: (v: typeof value) => void; info: ProvidersInfo; isNew: boolean }) {
  const set = (k: string, v: unknown) => onChange({ ...value, [k]: v });
  return (
    <div className="col" style={{ gap: 12 }}>
      <label className="fld"><span>Name (used in the routing order)</span><input className="inp sm mono" value={value.name} disabled={!isNew} onChange={(e) => set("name", e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 32))} /></label>
      <label className="fld"><span>Label</span><input className="inp sm" value={value.label ?? ""} onChange={(e) => set("label", e.target.value)} /></label>
      <div className="fld"><span>API dialect</span><div className="seg">{info.styles.map((s) => <button key={s} className={value.style === s ? "on" : ""} onClick={() => set("style", s)}>{STYLE_TEXT[s]}</button>)}</div></div>
      <label className="fld"><span>Base URL</span><input className="inp sm mono" value={value.base_url ?? ""} placeholder="https://api.example.com/v1" onChange={(e) => set("base_url", e.target.value)} /></label>
      <label className="fld"><span>How the key is sent</span>
        <Select size="sm" value={value.auth ?? "bearer"} onChange={(v) => set("auth", v)} options={info.auths.map((a) => ({ value: a, label: AUTH_TEXT[a] }))} /></label>
      {value.auth === "api-key" && <label className="fld"><span>Header name</span><input className="inp sm mono" value={value.header ?? ""} placeholder="api-key" onChange={(e) => set("header", e.target.value)} /></label>}
      <label className="fld"><span>Extra query (optional)</span><input className="inp sm mono" value={value.query ?? ""} placeholder="api-version=2024-10-21" onChange={(e) => set("query", e.target.value)} /></label>
      <div className="row" style={{ gap: 10 }}>
        {(["rpm", "rpd", "tpm"] as const).map((k) => (
          <label key={k} className="fld grow"><span>{k === "rpm" ? "Requests / min" : k === "rpd" ? "Requests / day" : "Tokens / min"}</span>
            <input className="inp sm num" type="number" min={1} value={value[k] ?? ""} onChange={(e) => set(k, Number(e.target.value))} /></label>
        ))}
      </div>
      <span className="xs faint">Limits are per key: with two keys the agents may use twice as much before falling through to the next provider.</span>
    </div>
  );
}

function AddProvider({ info, onClose, onDone }: { info: ProvidersInfo; onClose: () => void; onDone: () => void }) {
  const app = useApp();
  const taken = new Set(info.providers.map((p) => p.name));
  const [pick, setPick] = useState<ProviderPreset | "custom" | null>(null);
  const [v, setV] = useState<Partial<Provider> & { name: string; rpm?: number; rpd?: number; tpm?: number }>({ name: "" });
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const choose = (p: ProviderPreset | "custom") => {
    setPick(p);
    setV(p === "custom" ? { name: "custom", label: "Custom provider", style: "openai", auth: "bearer", base_url: "", rpm: 30, rpd: 5000, tpm: 100000 }
      : { name: taken.has(p.name) ? `${p.name}2` : p.name, label: p.label, style: p.style, auth: p.auth, base_url: p.base_url, query: p.query ?? "", rpm: p.rpm, rpd: p.rpd, tpm: p.tpm, models: p.models });
  };
  const save = async () => {
    setBusy(true);
    try {
      if (taken.has(v.name)) throw new Error(`there is already a provider called ${v.name}`);
      await api.put(`/api/llm/providers/${v.name}`, { label: v.label, style: v.style, auth: v.auth, base_url: v.base_url, query: v.query ?? "", header: v.header ?? "", rpm: v.rpm, rpd: v.rpd, tpm: v.tpm, models: v.models ?? {}, enabled: true });
      if (key.trim() && v.auth !== "none") await api.post(`/api/llm/providers/${v.name}/keys`, { value: key.trim() });
      onDone();
      app.toast(`${v.label} added - pick its models, then add it to the fail-over order`, "ok");
      onClose();
    } catch (e) { app.toast(err(e), "error"); } finally { setBusy(false); }
  };
  return (
    <Drawer title="Add an AI provider" icon="sparkle" onClose={onClose} wide
      footer={pick ? <><button className="btn sec" onClick={() => setPick(null)}>Back</button><span className="spacer" /><button className="btn" disabled={busy || !v.name || !v.base_url} onClick={save}><Icon name={busy ? "loading" : "check"} className={`sm ${busy ? "spin" : ""}`} />Add provider</button></> : undefined}>
      {!pick ? (
        <div className="col" style={{ gap: 12 }}>
          <span className="small muted">Pick a service, or set up any OpenAI-compatible or Anthropic endpoint yourself.</span>
          <div className="preset-grid">
            {info.presets.filter((p) => p.name !== "ollama").map((p) => (
              <button key={p.name} className="preset" onClick={() => choose(p)}>
                <b>{p.label}{taken.has(p.name) && <span className="tag xs">added</span>}</b>
                <small>{p.note}</small>
                <span className="xs faint mono">{STYLE_TEXT[p.style]}</span>
              </button>
            ))}
            <button className="preset custom" onClick={() => choose("custom")}><b><Icon name="add" className="xs" /> Custom provider</b><small>Any OpenAI-compatible or Anthropic API - your own URL.</small></button>
          </div>
        </div>
      ) : (
        <div className="col" style={{ gap: 14 }}>
          <ProviderForm value={v} onChange={setV} info={info} isNew />
          {v.auth !== "none" && <label className="fld"><span>API key (optional now - add more later)</span><input className="inp sm mono" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} /></label>}
          {pick !== "custom" && pick.keys_url && <a className="xs" href={pick.keys_url} target="_blank" rel="noreferrer noopener">Get an API key from {pick.label}</a>}
        </div>
      )}
    </Drawer>
  );
}

function EditProvider({ p, info, onClose, onDone }: { p: Provider; info: ProvidersInfo; onClose: () => void; onDone: () => void }) {
  const app = useApp();
  const [v, setV] = useState<Partial<Provider> & { name: string; rpm?: number; rpd?: number; tpm?: number }>({
    name: p.name, label: p.label, style: p.style, auth: p.auth, base_url: p.base_url, header: p.header, query: p.query,
    rpm: p.limits.requests_per_minute ?? 10, rpd: p.limits.requests_per_day ?? 1000, tpm: p.limits.tokens_per_minute ?? 6000,
  });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/api/llm/providers/${p.name}`, { label: v.label, style: v.style, auth: v.auth, base_url: v.base_url, header: v.header ?? "", query: v.query ?? "", rpm: v.rpm, rpd: v.rpd, tpm: v.tpm });
      onDone(); app.toast(`${v.label} saved`, "ok"); onClose();
    } catch (e) { app.toast(err(e), "error"); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!confirm(`Remove ${p.label}? Its keys stay in .env until you remove them.`)) return;
    try { await api.del(`/api/llm/providers/${p.name}`); onDone(); app.toast(`${p.label} removed`, "ok"); onClose(); } catch (e) { app.toast(err(e), "error"); }
  };
  return (
    <Drawer title={`Edit ${p.label}`} icon="edit" onClose={onClose}
      footer={<><button className="btn ghost danger" onClick={remove}><Icon name="trash" className="sm" />Remove</button><span className="spacer" /><button className="btn sec" onClick={onClose}>Cancel</button><button className="btn" disabled={busy || !v.base_url} onClick={save}><Icon name={busy ? "loading" : "check"} className={`sm ${busy ? "spin" : ""}`} />Save</button></>}>
      <ProviderForm value={v} onChange={setV} info={info} isNew={false} />
      {p.source !== "app" && <span className="xs faint">This provider comes from agent_settings.yaml; your changes are kept in llm_providers.json and win over the file.</span>}
    </Drawer>
  );
}

function Routes({ info }: { info: ProvidersInfo }) {
  const [r, setR] = useState(info.routes);
  const qc = useQueryClient();
  const app = useApp();
  useEffect(() => setR(info.routes), [info.routes]);
  const byName = new Map(info.providers.map((p) => [p.name, p]));
  const move = (tier: string, i: number, d: number) => { const l = [...(r[tier] ?? [])]; const j = i + d; if (j < 0 || j >= l.length) return; [l[i], l[j]] = [l[j], l[i]]; setR({ ...r, [tier]: l }); };
  const drop = (tier: string, i: number) => setR({ ...r, [tier]: (r[tier] ?? []).filter((_, j) => j !== i) });
  const add = (tier: string, name: string) => setR({ ...r, [tier]: [...(r[tier] ?? []), `${name}:${tier}`] });
  const dirty = JSON.stringify(r) !== JSON.stringify(info.routes);
  const save = async () => { try { await api.put("/api/llm/routes", r); qc.invalidateQueries({ queryKey: ["providers"] }); app.toast("Fail-over order saved", "ok"); } catch (e) { app.toast(err(e), "error"); } };
  return (
    <Panel title="Fail-over order" meta="the first provider with a working key answers; on a limit or error the next takes over"
      tools={<>{dirty && <button className="btn xs ghost" onClick={() => setR(info.routes)}>Discard</button>}<button className="btn xs" disabled={!dirty} onClick={save}>Save order</button></>}>
      <div className="grid c2">
        {(["fast", "smart"] as const).map((tier) => {
          const listed = new Set((r[tier] ?? []).map((s) => s.split(":")[0]));
          const rest = info.providers.filter((p) => !listed.has(p.name));
          return (
            <div key={tier}>
              <div className="label" style={{ marginBottom: 6 }}>{tier === "fast" ? "Fast tasks" : "Smart tasks"}</div>
              {(r[tier] ?? []).map((s, i) => {
                const p = byName.get(s.split(":")[0]);
                return (
                  <div key={s} className="route-row">
                    <span className="mono faint" style={{ width: 16 }}>{i + 1}</span><span className={`dot ${p?.enabled && p.has_key ? "ok" : ""}`} />
                    <span className="grow ellipsis">{p?.label ?? s.split(":")[0]}{p ? <span className="xs faint mono"> · {p.models[s.split(":")[1]] || "no model chosen"}</span> : <span className="xs down"> · not configured</span>}</span>
                    <button className="ibtn sm" onClick={() => move(tier, i, -1)} disabled={i === 0} title="Earlier"><Icon name="arrow-up" className="xs" /></button>
                    <button className="ibtn sm" onClick={() => move(tier, i, 1)} disabled={i === (r[tier]?.length ?? 0) - 1} title="Later"><Icon name="arrow-down" className="xs" /></button>
                    <button className="ibtn sm" onClick={() => drop(tier, i)} title="Take out of the order"><Icon name="close" className="xs" /></button>
                  </div>
                );
              })}
              {rest.length > 0 && (
                <div style={{ marginTop: 8 }}><ActionMenu small label="Add a provider" icon="add" items={rest.map((p) => ({ label: p.label, onClick: () => add(tier, p.name) }))} /></div>
              )}
            </div>
          );
        })}
      </div>
      <span className="xs faint">Providers left out of the order are still tried last, if they have a key.</span>
    </Panel>
  );
}
