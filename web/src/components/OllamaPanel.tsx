import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ModelTestResult, OllamaCatalogItem, OllamaStatus } from "../lib/api";
import { ErrorNote, Icon, Loading, Panel, Toggle } from "./ui";
import { useApp } from "./workbenchContext";

const err = (e: unknown) => (e instanceof Error ? e.message : String(e));
const GB = 1024 ** 3;
const bytes = (n: number | null | undefined) => (n == null ? "-" : n >= GB ? `${(n / GB).toFixed(1)} GB` : `${Math.max(1, Math.round(n / 1024 ** 2))} MB`);
const BUDGETS = [1, 2, 5, 10, 0] as const; // GB of disk the user can spare; 0 = no limit

/** Local models through Ollama: switch it on, pick or download a model, start it with INTVAL. */
export function OllamaPanel() {
  const app = useApp();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["ollama"],
    queryFn: () => api.get<OllamaStatus>("/api/ollama"),
    // poll fast while a download runs, slowly otherwise (Ollama may be started outside INTVAL)
    refetchInterval: (query) => (Object.values(query.state.data?.pulls ?? {}).some((p) => !p.done) ? 1200 : 10_000),
  });
  const [busy, setBusy] = useState<string | null>(null);
  const set = (d: OllamaStatus) => { qc.setQueryData(["ollama"], d); qc.invalidateQueries({ queryKey: ["providers"] }); qc.invalidateQueries({ queryKey: ["status"] }); };
  const act = async (what: string, fn: () => Promise<OllamaStatus>, ok?: string) => {
    setBusy(what);
    try { set(await fn()); if (ok) app.toast(ok, "ok"); } catch (e) { app.toast(err(e), "error"); } finally { setBusy(null); }
  };
  const save = (patch: Record<string, unknown>, ok: string) => act(Object.keys(patch)[0], () => api.put<OllamaStatus>("/api/ollama/settings", patch), ok);

  const d = q.data;
  const meta = !d ? "" : !d.installed ? "not installed" : d.running ? `running · v${d.version} · ${d.models.length} model${d.models.length === 1 ? "" : "s"}` : "installed · not running";
  return (
    <Panel title="Local models (Ollama)" meta={meta} noExport
      tools={d && <Toggle checked={d.enabled} disabled={busy === "enabled" || (!d.enabled && !d.models.length)} label={d.enabled ? "On" : "Off"}
        onChange={(v) => save({ enabled: v }, v ? "Ollama switched on - the agents can use local models" : "Ollama switched off")} />}>
      {q.isLoading && <Loading rows={3} />}
      {q.isError && <ErrorNote error={q.error} onRetry={() => q.refetch()} />}
      {d && (
        <div className="col" style={{ gap: 16 }}>
          <div className="note inf"><Icon name="device-desktop" /><div>Ollama runs open models <b>on this computer</b>: free, private and with no API key or daily limit. It is slower than the cloud on most laptops, so it works best as a fallback - or first, if you'd rather nothing leaves your machine.</div></div>
          <Status d={d} busy={busy} onStart={() => act("start", () => api.post<OllamaStatus>("/api/ollama/start"), "Ollama is running")} />
          <div className="ol-opts">
            <Toggle checked={d.autostart} disabled={busy === "autostart"} onChange={(v) => save({ autostart: v }, v ? "Ollama will open whenever INTVAL starts" : "Ollama will no longer open with INTVAL")}
              label={<span>Open Ollama whenever INTVAL starts <span className="faint xs">· it stays open after INTVAL stops</span></span>} />
            <Toggle checked={d.prefer_local} disabled={busy === "prefer_local" || !d.enabled} onChange={(v) => save({ prefer_local: v }, v ? "Local models are tried first" : "Cloud providers are tried first; Ollama is the fallback")}
              label={<span>Try local models before cloud providers <span className="faint xs">· otherwise Ollama is the fallback</span></span>} />
          </div>
          {d.running && <Installed d={d} busy={busy} onSave={save} onDelete={(m) => act(`del:${m}`, () => api.del<OllamaStatus>(`/api/ollama/models?model=${encodeURIComponent(m)}`), `${m} deleted`)} />}
          <Pulls d={d} onDismiss={(m) => act(`dismiss:${m}`, () => api.del<OllamaStatus>(`/api/ollama/pull?model=${encodeURIComponent(m)}`))} />
          {d.installed && <Catalog d={d} busy={busy} onPull={(m) => act(`pull:${m}`, () => api.post<OllamaStatus>("/api/ollama/pull", { model: m }), `Downloading ${m}…`)} />}
        </div>
      )}
    </Panel>
  );
}

function Status({ d, busy, onStart }: { d: OllamaStatus; busy: string | null; onStart: () => void }) {
  if (!d.installed) {
    return (
      <div className="ol-status">
        <span className="dot bad" /><div className="grow"><b>Ollama is not installed.</b><div className="xs faint">Install it once (free, about 1 GB with its runtime), then come back: INTVAL finds it automatically.</div></div>
        <a className="btn xs" href={d.download_url} target="_blank" rel="noreferrer noopener"><Icon name="link-external" className="xs" />Download Ollama</a>
      </div>
    );
  }
  const free = d.disk.free, total = d.disk.total;
  return (
    <div className="ol-status">
      <span className={`dot ${d.running ? "ok" : ""}`} />
      <div className="grow">
        <b>{d.running ? `Ollama ${d.version} is running` : "Ollama is installed but not running"}</b>
        <div className="xs faint mono ellipsis" title={d.disk.path}>models in {d.disk.path}</div>
      </div>
      {free != null && total != null && (
        <div className="ol-disk" title={`${bytes(free)} free of ${bytes(total)}`}>
          <span className="xs faint">{bytes(free)} free</span>
          <div className="meter" style={{ width: 120 }}><span style={{ width: `${Math.round((1 - free / total) * 100)}%`, background: free < 5 * GB ? "var(--down)" : "var(--accent)" }} /></div>
        </div>
      )}
      {!d.running && <button className="btn xs" disabled={busy === "start"} onClick={onStart}><Icon name={busy === "start" ? "loading" : "play"} className={`xs ${busy === "start" ? "spin" : ""}`} />Start Ollama</button>}
    </div>
  );
}

function Installed({ d, busy, onSave, onDelete }: { d: OllamaStatus; busy: string | null; onSave: (patch: Record<string, unknown>, ok: string) => void; onDelete: (m: string) => void }) {
  const [test, setTest] = useState<Record<string, ModelTestResult | "busy">>({});
  const run = async (m: string) => {
    setTest((t) => ({ ...t, [m]: "busy" }));
    try { const r = await api.post<ModelTestResult>("/api/llm/test", { provider: "ollama", model: m }); setTest((t) => ({ ...t, [m]: r })); }
    catch (e) { setTest((t) => ({ ...t, [m]: { ok: false, status: null, seconds: 0, error: err(e) } })); }
  };
  if (!d.models.length) {
    return <div className="empty" style={{ padding: 16 }}><span className="small">No models downloaded yet. Pick one below - <b>llama3.2:3b</b> is a good start.</span></div>;
  }
  const choose = (tier: "fast" | "smart", m: string) => onSave({ models: { ...d.chosen, [tier]: m } }, `Ollama ${tier} model → ${m}`);
  return (
    <div>
      <div className="label prov-l">Downloaded models <span className="faint">· choose which one the agents use for each kind of task</span></div>
      <div className="ol-tiers">
        {(["fast", "smart"] as const).map((tier) => (
          <label key={tier} className="fld grow"><span>{tier === "fast" ? "Fast model (bulk reading)" : "Smart model (reasoning and writing)"}</span>
            <select className="sel sm" value={d.chosen[tier] ?? ""} disabled={busy === "models"} onChange={(e) => e.target.value && choose(tier, e.target.value)}>
              {!d.chosen[tier] && <option value="">- choose -</option>}
              {d.models.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
            </select></label>
        ))}
      </div>
      <div className="scroll-x" style={{ marginTop: 8 }}>
        <table className="dg dense">
          <thead><tr><th>Model</th><th>Size</th><th>Parameters</th><th>Used for</th><th className="r" /></tr></thead>
          <tbody>
            {d.models.map((m) => {
              const t = test[m.name];
              const uses = (["fast", "smart"] as const).filter((tier) => d.chosen[tier] === m.name);
              return (
                <tr key={m.name}>
                  <td><div className="co"><b className="mono">{m.name}</b><small>{[m.family, m.quant].filter(Boolean).join(" · ")}</small></div></td>
                  <td className="mono">{bytes(m.size)}</td>
                  <td className="mono">{m.params || "-"}</td>
                  <td>{uses.length ? uses.map((u) => <span key={u} className="tag xs" style={{ marginRight: 4 }}>{u}</span>) : <span className="faint xs">-</span>}</td>
                  <td className="r">
                    {t && t !== "busy" && <span className={`xs ${t.ok ? "up" : "down"}`} title={t.error ?? t.reply ?? ""} style={{ marginRight: 6 }}>{t.ok ? `✓ ${t.seconds}s` : "✗ failed"}</span>}
                    <button className="ibtn sm" onClick={() => run(m.name)} disabled={t === "busy"} title="Test: ask it a tiny JSON question"><Icon name={t === "busy" ? "loading" : "beaker"} className={`xs ${t === "busy" ? "spin" : ""}`} /></button>
                    <button className="ibtn sm" disabled={busy === `del:${m.name}`} title="Delete this model from disk"
                      onClick={() => { if (confirm(`Delete ${m.name}? This frees ${bytes(m.size)}; you can download it again later.`)) onDelete(m.name); }}><Icon name="trash" className="xs" /></button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Pulls({ d, onDismiss }: { d: OllamaStatus; onDismiss: (m: string) => void }) {
  const list = Object.entries(d.pulls);
  if (!list.length) return null;
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="label">Downloads</div>
      {list.map(([m, p]) => {
        const pct = p.total ? Math.min(100, Math.round((p.completed / p.total) * 100)) : 0;
        return (
          <div key={m} className="ol-pull">
            <div className="row" style={{ gap: 8 }}>
              <Icon name={p.error ? "error" : p.done ? "pass" : "cloud-download"} className={`xs ${p.error ? "down" : p.done ? "up" : ""}`} />
              <b className="mono">{m}</b>
              <span className="xs faint grow ellipsis">{p.error ? p.error : p.done ? "downloaded - ready to use" : `${p.status}${p.total ? ` · ${bytes(p.completed)} of ${bytes(p.total)}` : ""}`}</span>
              {!p.done && p.total > 0 && <span className="mono xs">{pct}%</span>}
              {p.done && <button className="ibtn sm" onClick={() => onDismiss(m)} title="Dismiss"><Icon name="close" className="xs" /></button>}
            </div>
            {!p.done && <div className="meter" style={{ marginTop: 6 }}><span style={{ width: `${pct}%`, background: "var(--accent)" }} /></div>}
          </div>
        );
      })}
    </div>
  );
}

function Catalog({ d, busy, onPull }: { d: OllamaStatus; busy: string | null; onPull: (m: string) => void }) {
  const [budget, setBudget] = useState<number>(() => {
    const free = (d.disk.free ?? 0) / GB;
    return BUDGETS.find((b) => b && b * 4 >= free) ?? 5; // something sensible for this disk
  });
  const [custom, setCustom] = useState("");
  const have = new Set(d.models.map((m) => m.name.replace(/:latest$/, "")));
  const freeGb = d.disk.free != null ? d.disk.free / GB : Infinity;
  const shown = useMemo(() => d.catalog.filter((c) => !budget || c.size_gb <= budget), [d.catalog, budget]);
  const pulling = (m: string) => !!d.pulls[m] && !d.pulls[m].done;
  return (
    <div>
      <div className="row" style={{ gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        <div className="label grow">Download a free model</div>
        <span className="xs faint">Storage I can spare</span>
        <div className="seg">{BUDGETS.map((b) => <button key={b} className={budget === b ? "on" : ""} onClick={() => setBudget(b)}>{b ? `≤ ${b} GB` : "Any"}</button>)}</div>
      </div>
      <div className="preset-grid">
        {shown.map((c: OllamaCatalogItem) => {
          const got = have.has(c.name);
          const tooBig = c.size_gb > freeGb;
          return (
            <div key={c.name} className={`preset ol-card ${got ? "got" : ""}`}>
              <b><span className="mono">{c.name}</span>{got && <span className="tag xs">downloaded</span>}</b>
              <small>{c.note}</small>
              <span className="xs faint">{c.family} · {c.params} · {c.size_gb < 1 ? `${Math.round(c.size_gb * 1024)} MB` : `${c.size_gb} GB`} download · {c.ram_gb} GB RAM</span>
              {!got && (
                <button className="btn xs sec" style={{ marginTop: 4 }} disabled={pulling(c.name) || busy === `pull:${c.name}` || tooBig || !d.running}
                  title={tooBig ? "Not enough free disk space" : !d.running ? "Start Ollama first" : `Download ${c.name}`} onClick={() => onPull(c.name)}>
                  <Icon name={pulling(c.name) ? "loading" : "cloud-download"} className={`xs ${pulling(c.name) ? "spin" : ""}`} />{pulling(c.name) ? "Downloading…" : tooBig ? "Not enough space" : "Download"}
                </button>
              )}
            </div>
          );
        })}
        {!shown.length && <span className="xs faint">No listed model fits in that much space - raise the limit.</span>}
      </div>
      <div className="row" style={{ marginTop: 10, gap: 6 }}>
        <input className="inp sm mono grow" placeholder="or any model from the Ollama library, e.g. phi3:mini" value={custom}
          onChange={(e) => setCustom(e.target.value.trim())} onKeyDown={(e) => { if (e.key === "Enter" && custom && d.running) { onPull(custom); setCustom(""); } }} />
        <button className="btn xs" disabled={!custom || !d.running} onClick={() => { onPull(custom); setCustom(""); }}><Icon name="cloud-download" className="xs" />Download</button>
        <a className="xs" href={d.library_url} target="_blank" rel="noreferrer noopener">Browse the library</a>
      </div>
    </div>
  );
}
