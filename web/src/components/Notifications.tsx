import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, JobSummary } from "../lib/api";
import { useIntel, useStatus } from "../lib/hooks";
import { LiveAlert, useLiveAlerts } from "../lib/live";
import { chime, desktop, dismiss, getPrefs, setPrefs, useDismissed, useNotifyPrefs } from "../lib/notify";
import { alertEvent } from "../lib/sound";
import { NotifySettings } from "./NotifySettings";
import { ExportButton } from "./ExportButton";
import { ago, shortName, slug } from "../lib/format";
import { Icon, Popover, Toggle } from "./ui";
import { Link } from "react-router-dom";
import { useApp } from "./workbenchContext";
import { jobTitle } from "./Shell";

type Tab = "all" | "live" | "research";
interface Item { key: string; kind: "live" | "research"; icon: string; tone: string; title: string; text: string; t: number | null; isNew: boolean; go: string; alert?: LiveAlert }

const LIVE_ICON: Record<string, [string, string]> = {
  buy_below: ["tag", "up"], below: ["arrow-down", "down"], above: ["arrow-up", "up"], move: ["pulse", "warn"],
};
const LAST = "intval.alerts.notified";

/** The bell: notifications panel, plus the watcher that announces new alerts and finished runs. */
export function Notifications() {
  const live = useLiveAlerts();
  const intel = useIntel();
  const prefs = useNotifyPrefs();
  const dismissed = useDismissed();
  useWatchers();

  const research = useMemo(() => {
    const v = intel.data?.verdicts ?? [];
    const run = intel.data?.meta?.run_id ?? "";
    const at = intel.data?.meta?.started ? Date.parse(intel.data.meta.started) / 1000 : null;
    const rows: Item[] = [];
    for (const x of v) {
      for (const f of x.red_flags ?? []) rows.push({ key: `${run}|${x.company}|${f}`, kind: "research", icon: "warning", tone: "down", title: shortName(x.company), text: f, t: at, isNew: false, go: `/coverage/${slug(x.company)}` });
      for (const c of (x.changes ?? []).filter((c) => !c.startsWith("first")))
        rows.push({ key: `${run}|${x.company}|${c}`, kind: "research", icon: c.startsWith("label") ? "tag" : "history", tone: "info", title: shortName(x.company), text: c, t: at, isNew: false, go: `/coverage/${slug(x.company)}` });
    }
    return rows.filter((r) => !dismissed.has(r.key));
  }, [intel.data, dismissed]);
  const liveItems = useMemo<Item[]>(() => (live.data ?? []).map((a) => {
    const [icon, tone] = LIVE_ICON[a.kind] ?? ["bell", "info"];
    return { key: `live|${a.id}`, kind: "live", icon, tone, title: shortName(a.name), text: a.message.replace(a.name, "").trim().replace(/^is /, ""), t: a.t, isNew: !a.seen, go: `/watchlist?t=${encodeURIComponent(a.ticker)}`, alert: a };
  }), [live.data]);

  const unseen = liveItems.filter((i) => i.isNew).length;
  const count = prefs.enabled ? unseen + (prefs.research ? research.length : 0) : 0;
  return (
    <Popover className="pop notif" trigger={(open, toggle) => (
      <button className={`tool ${open ? "on" : ""}`} title={prefs.enabled ? "Notifications" : "Notifications are off"} onClick={toggle}>
        <Icon name={prefs.enabled ? (unseen ? "bell-dot" : "bell") : "bell-slash"} />
        {count > 0 && <span className="pip">{count > 99 ? "99+" : count}</span>}
      </button>
    )}>
      {(close) => <Panel live={liveItems} research={research} close={close} />}
    </Popover>
  );
}

function Panel({ live, research, close }: { live: Item[]; research: Item[]; close: () => void }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const prefs = useNotifyPrefs();
  const [tab, setTab] = useState<Tab>(() => (live.some((i) => i.isNew) || !research.length ? "live" : "all"));
  const [settings, setSettings] = useState(false);
  const [gone, setGone] = useState<Set<string>>(new Set()); // removed, waiting for the server

  // opening the panel counts as reading the live alerts
  useEffect(() => {
    if (!live.some((i) => i.isNew)) return;
    const t = window.setTimeout(() => api.post("/api/live/alerts/seen").then(() => qc.invalidateQueries({ queryKey: ["live-alerts"] })).catch(() => undefined), 1500);
    return () => window.clearTimeout(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const items = (tab === "live" ? live : tab === "research" ? research : [...live, ...research]).filter((i) => !gone.has(i.key));
  const refresh = () => qc.invalidateQueries({ queryKey: ["live-alerts"] });
  const remove = (i: Item) => {
    setGone((g) => new Set(g).add(i.key));
    chime("ui");
    if (i.alert) api.del(`/api/live/alerts/${i.alert.id}`).then(refresh).catch(refresh);
    else dismiss([i.key]);
  };
  const clearAll = () => {
    const ls = items.filter((i) => i.kind === "live"), rs = items.filter((i) => i.kind === "research");
    setGone((g) => new Set([...g, ...items.map((i) => i.key)]));
    chime("ui");
    if (rs.length) dismiss(rs.map((i) => i.key));
    if (ls.length) {
      if (ls.length === live.length) api.del("/api/live/alerts").then(refresh).catch(refresh);
      else Promise.all(ls.map((i) => api.del(`/api/live/alerts/${i.alert!.id}`))).then(refresh).catch(refresh);
    }
  };
  const toggleAll = (on: boolean) => { setPrefs({ enabled: on }); if (on) chime("ui"); };

  return (
    <div className="nt-wrap">
      <div className="nt-head">
        <b>Notifications</b>
        <span className="spacer" />
        <Toggle checked={prefs.enabled} onChange={toggleAll} label={<span className="xs muted">{prefs.enabled ? "On" : "Off"}</span>} />
        <button className={`ibtn sm ${prefs.sound && prefs.enabled ? "" : "faint"}`} title={prefs.sound ? "Mute sounds" : "Turn sounds on"}
          onClick={() => { const on = !prefs.sound; setPrefs({ sound: on }); if (on) chime("ui"); }}>
          <Icon name={prefs.sound ? "unmute" : "mute"} className="sm" />
        </button>
        <button className={`ibtn sm ${settings ? "on" : ""}`} title="Notification settings" onClick={() => setSettings(!settings)}><Icon name="settings-gear" className="sm" /></button>
      </div>
      {settings ? <div className="nt-set"><NotifySettings /><Link className="xs" to="/configuration?section=notify">Open in Configuration</Link></div> : (
        <>
          <div className="nt-tabs">
            {([["all", "All", live.length + research.length], ["live", "Live prices", live.length], ["research", "Research", research.length]] as const).map(([id, l, n]) => (
              <button key={id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>{l}<span className="n">{n}</span></button>
            ))}
            <span className="spacer" />
            <ExportButton title="Notifications" className="ibtn sm" table={() => ({ head: ["Kind", "Company", "Message", "When"], rows: items.map((i) => [i.kind === "live" ? "Live price" : "Research", i.title, i.text, i.t ? new Date(i.t * 1000).toLocaleString("en-IN") : ""]) })} />
            <button className="nt-clear" disabled={!items.length} onClick={clearAll} title="Remove everything in this tab"><Icon name="clear-all" className="xs" />Clear all</button>
          </div>
          {!prefs.enabled && (
            <div className="nt-off"><Icon name="bell-slash" className="sm" /><span>Notifications are off: no badge, sounds or pop-ups. Alerts are still recorded here.</span></div>
          )}
          <div className="nt-list">
            {items.length === 0 ? (
              <div className="empty" style={{ padding: 32 }}><Icon name="pass" className="up" /><span className="small">You're all caught up.</span></div>
            ) : items.slice(0, 150).map((i) => (
              <div key={i.key} className={`nt ${i.isNew ? "new" : ""}`} onClick={() => { close(); nav(i.go); }}>
                <span className={`ic ${i.tone}`}><Icon name={i.icon} className="sm" /></span>
                <div className="body">
                  <div className="t"><b>{i.title}</b>{i.isNew && <span className="dotnew" />}</div>
                  <div className="d">{i.text}</div>
                  <div className="m">{i.kind === "live" ? "Live price" : "Research"} · {ago(i.t)}</div>
                </div>
                <button className="x" title={i.kind === "live" ? "Delete" : "Dismiss"} onClick={(e) => { e.stopPropagation(); remove(i); }}><Icon name="close" className="xs" /></button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** Announce new live alerts and finished runs: sound, a toast and (if allowed) a desktop pop-up. */
function useWatchers() {
  const live = useLiveAlerts();
  const status = useStatus();
  const app = useApp();
  const last = useRef<number | null>(null);
  const prevJob = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    const list = live.data;
    if (!list) return;
    const max = list.reduce((m, a) => Math.max(m, a.id), 0);
    if (last.current == null) {
      let stored = 0;
      try { stored = Number(localStorage.getItem(LAST) || 0); } catch { /* storage blocked */ }
      last.current = stored || max; // first visit ever: do not replay old alerts
    }
    const fresh = list.filter((a) => a.id > last.current!).sort((a, b) => a.id - b.id);
    if (max > last.current) { last.current = max; try { localStorage.setItem(LAST, String(max)); } catch { /* private mode */ } }
    if (!fresh.length) return;
    if (!getPrefs().enabled) return;
    const top = fresh.find((a) => a.kind === "buy_below") ?? fresh[fresh.length - 1];
    chime(alertEvent(top.kind));
    fresh.slice(-3).forEach((a) => app.toast(a.message, a.kind === "buy_below" ? "ok" : "info"));
    if (fresh.length > 3) app.toast(`…and ${fresh.length - 3} more price alerts`);
    fresh.slice(-3).forEach((a) => desktop(`INTVAL · ${shortName(a.name)}`, a.message, `alert-${a.id}`));
  }, [live.data, app]);

  useEffect(() => {
    const active = status.data?.active_job?.id ?? null;
    if (prevJob.current === undefined) { prevJob.current = active; return; }
    const ended = prevJob.current;
    prevJob.current = active;
    if (!ended || active) return;
    // the jobs list may lag a poll behind: ask for this job's final state
    api.get<JobSummary>(`/api/jobs/${ended}`).then((j) => {
      if (j.status === "cancelled" || j.status === "running") return;
      const ok = j.status === "succeeded";
      const name = jobTitle(j.kind, j.opts);
      chime(ok ? "job_done" : "job_failed");
      app.toast(`${name} ${ok ? "finished" : "failed"}`, ok ? "ok" : "error");
      desktop(`INTVAL · ${name}`, ok ? "Finished" : "Failed — open Operations for the log", `job-${j.id}`);
    }).catch(() => undefined);
  }, [status.data?.active_job?.id, app]); // eslint-disable-line react-hooks/exhaustive-deps
}
