import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Icon, Panel, Toggle } from "./ui";
import { useApp } from "./workbenchContext";

interface Source { key: string; label: string; supplies: string[]; env: string | null; about: string; url: string; on: boolean; has_key: boolean; position: number }

const SUPPLIES: Record<string, string> = { statements: "accounts", prices: "prices", quotes: "live quotes", sectors: "sector lists" };

/**
 * Where company data comes from, in the order it is trusted. The first source
 * that has a figure supplies it; later ones fill only what is still missing,
 * so turning more on never overwrites a figure, it only fills gaps.
 */
export function DataSources() {
  const q = useQuery({ queryKey: ["data-sources"], queryFn: () => api.get<{ providers: Source[] }>("/api/data-sources") });
  const qc = useQueryClient();
  const app = useApp();
  const list = q.data?.providers ?? [];
  const save = (order: string[], off: string[]) => api.put<{ providers: Source[] }>("/api/data-sources", { order, off })
    .then((r) => qc.setQueryData(["data-sources"], r)).catch((e) => app.toast(e instanceof Error ? e.message : String(e), "error"));
  const order = list.map((s) => s.key);
  const off = list.filter((s) => !s.on).map((s) => s.key);
  const move = (i: number, d: -1 | 1) => { const o = [...order]; [o[i], o[i + d]] = [o[i + d], o[i]]; save(o, off); };
  const toggle = (k: string, on: boolean) => save(order, on ? off.filter((x) => x !== k) : [...off, k]);
  return (
    <Panel title="Data sources" meta="the first source with a figure supplies it; the next ones fill what is still missing" flush>
      <div className="ds-list">
        {list.map((s, i) => (
          <div key={s.key} className={`ds ${s.on ? "" : "off"}`}>
            <div className="ds-order">
              <button className="ibtn sm" disabled={i === 0} onClick={() => move(i, -1)} title="Trust it more (move up)" aria-label={`Move ${s.label} up`}><Icon name="chevron-up" className="xs" /></button>
              <span className="mono xs faint">{i + 1}</span>
              <button className="ibtn sm" disabled={i === list.length - 1} onClick={() => move(i, 1)} title="Trust it less (move down)" aria-label={`Move ${s.label} down`}><Icon name="chevron-down" className="xs" /></button>
            </div>
            <div className="ds-main">
              <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                <b>{s.label}</b>
                {s.supplies.map((x) => <span key={x} className="tag xs">{SUPPLIES[x] ?? x}</span>)}
                {s.env ? (s.has_key ? <span className="tag up xs">key set</span> : <span className="tag warn xs">needs a free key</span>) : <span className="tag xs">no key needed</span>}
              </div>
              <div className="xs muted">{s.about} <a href={s.url} target="_blank" rel="noreferrer noopener">{s.url.replace(/^https?:\/\//, "").split("/")[0]}</a></div>
              {s.env && <KeyField env={s.env} has={s.has_key} />}
            </div>
            <Toggle checked={s.on} onChange={(v) => toggle(s.key, v)} label={s.on ? "On" : "Off"} />
          </div>
        ))}
      </div>
      <div className="fc-note xs faint"><Icon name="info" className="xs" />Yahoo Finance has only about four years of accounts for most Indian companies; Screener.in fills the older years. The NSE and BSE websites take over prices and live quotes when Yahoo has none. A source that does not answer is skipped — nothing ever stops a run. Changes apply to the next run.</div>
    </Panel>
  );
}

function KeyField({ env, has }: { env: string; has: boolean }) {
  const [v, setV] = useState("");
  const qc = useQueryClient();
  const app = useApp();
  const put = (value: string) => api.put("/api/settings/keys", { values: { [env]: value } })
    .then(() => { setV(""); app.toast(value ? `${env} saved` : `${env} removed`, "ok"); qc.invalidateQueries({ queryKey: ["data-sources"] }); })
    .catch((e) => app.toast(e instanceof Error ? e.message : String(e), "error"));
  return (
    <div className="row" style={{ gap: 6, marginTop: 6 }}>
      <input className="inp sm mono" style={{ width: 260 }} type="password" autoComplete="off" value={v} placeholder={has ? "•••••••• (saved) - paste to replace" : `${env}`} onChange={(e) => setV(e.target.value)} />
      <button className="btn xs" disabled={!v.trim()} onClick={() => put(v.trim())}>Save</button>
      {has && <button className="btn xs ghost" onClick={() => put("")}>Remove</button>}
    </div>
  );
}
