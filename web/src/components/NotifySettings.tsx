import { inQuietHours, resetPrefs, setEvent, setPrefs, useNotifyPrefs } from "../lib/notify";
import { EVENTS, playPreset, PRESETS } from "../lib/sound";
import { Icon, Toggle } from "./ui";
import { Select } from "./Select";
import { useApp } from "./workbenchContext";

/** every half hour of the day, plus a time set before this list existed */
const HALF_HOURS = Array.from({ length: 48 }, (_, i) => `${String(i >> 1).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);
const timeOpts = (cur: string) => [...new Set([...HALF_HOURS, cur])].sort().map((t) => ({ value: t, label: t }));

/** Every notification setting. `wide` lays the cues out as a table (Configuration). */
export function NotifySettings({ wide = false }: { wide?: boolean }) {
  const p = useNotifyPrefs();
  const app = useApp();
  const perm = typeof Notification === "undefined" ? "unsupported" : Notification.permission;
  const setDesktop = async (on: boolean) => {
    if (!on) return setPrefs({ desktop: false });
    if (perm === "unsupported") return app.toast("This browser cannot show desktop notifications", "error");
    const r = perm === "granted" ? "granted" : await Notification.requestPermission();
    if (r === "granted") setPrefs({ desktop: true });
    else app.toast("Desktop notifications are blocked in the browser's site settings", "error");
  };
  const soundOff = !p.enabled || !p.sound;
  const quietNow = inQuietHours(p.quiet);
  return (
    <div className={`ns ${wide ? "wide" : ""}`}>
      <section>
        <div className="ns-h">General</div>
        <Row title="Notifications" sub="The badge, pop-ups and sounds. Alerts are always recorded.">
          <Toggle checked={p.enabled} onChange={(v) => setPrefs({ enabled: v })} />
        </Row>
        <Row title="Desktop pop-ups" sub="A Windows notification when this tab is in the background.">
          <Toggle checked={p.desktop} disabled={!p.enabled} onChange={setDesktop} />
        </Row>
        {perm === "denied" && <span className="xs warn">The browser blocks notifications for this site; allow them in its site settings.</span>}
        <Row title="Research alerts in the badge" sub="Red flags and changes from the latest research run.">
          <Toggle checked={p.research} onChange={(v) => setPrefs({ research: v })} />
        </Row>
      </section>

      <section>
        <div className="ns-h">Sound</div>
        <Row title="Sound effects" sub={quietNow ? "Quiet hours right now - sounds are held." : "Short, quiet cues; each event has its own below."}>
          <Toggle checked={p.sound} disabled={!p.enabled} onChange={(v) => setPrefs({ sound: v })} />
        </Row>
        <div className={`ns-vol ${soundOff ? "off" : ""}`}>
          <Icon name="mute" className="xs" />
          <input type="range" className="sl" min={0} max={1} step={0.05} value={p.volume} disabled={soundOff}
            onChange={(e) => setPrefs({ volume: Number(e.target.value) })} onPointerUp={() => playPreset("glass", p.volume)} />
          <Icon name="unmute" className="xs" />
          <span className="mono xs">{Math.round(p.volume * 100)}%</span>
        </div>
        <Row title="Quiet hours" sub="No sounds in this window; the badge still counts.">
          <Toggle checked={p.quiet.on} disabled={soundOff} onChange={(v) => setPrefs({ quiet: { ...p.quiet, on: v } })} />
        </Row>
        {p.quiet.on && (
          <div className="ns-quiet">
            <span className="row" style={{ gap: 6 }}>From <Select size="sm" value={p.quiet.from} ariaLabel="Quiet from" options={timeOpts(p.quiet.from)} onChange={(v) => setPrefs({ quiet: { ...p.quiet, from: v } })} /></span>
            <span className="row" style={{ gap: 6 }}>to <Select size="sm" value={p.quiet.to} ariaLabel="Quiet until" options={timeOpts(p.quiet.to)} onChange={(v) => setPrefs({ quiet: { ...p.quiet, to: v } })} /></span>
          </div>
        )}
      </section>

      <section>
        <div className="ns-h">Cues<span className="faint"> · one per event</span></div>
        <div className={`ns-cues ${soundOff ? "off" : ""}`}>
          {EVENTS.map((ev) => {
            const e = p.events[ev.id];
            return (
              <div key={ev.id} className={`ns-cue ${e.on ? "" : "muted"}`}>
                <div className="ns-cue-t">
                  <b>{ev.label}</b>
                  <span>{ev.desc}</span>
                </div>
                <div className="ns-cue-c">
                  <Select size="sm" value={e.preset} disabled={soundOff || !e.on} title={PRESETS[e.preset]?.hint} ariaLabel={`${ev.label} sound`}
                    onChange={(v) => { setEvent(ev.id, { preset: v }); playPreset(v, e.volume * p.volume || 0.5); }}
                    options={Object.entries(PRESETS).map(([k, v]) => ({ value: k, label: v.label }))} />
                  <input type="range" className="sl" min={0} max={1} step={0.05} value={e.volume} disabled={soundOff || !e.on}
                    onChange={(x) => setEvent(ev.id, { volume: Number(x.target.value) })} onPointerUp={() => playPreset(e.preset, e.volume * p.volume)} title={`${Math.round(e.volume * 100)}%`} />
                  <button className="ibtn sm" title="Preview" onClick={() => playPreset(e.preset, (e.volume * p.volume) || 0.5)} disabled={e.preset === "none"}><Icon name="play" className="xs" /></button>
                  <Toggle checked={e.on} disabled={soundOff} onChange={(v) => setEvent(ev.id, { on: v })} />
                </div>
              </div>
            );
          })}
        </div>
      </section>
      <div className="row ns-foot">
        <button className="btn xs ghost" onClick={() => { resetPrefs(); app.toast("Notification settings reset"); }}><Icon name="discard" className="xs" />Reset to defaults</button>
        <span className="spacer" />
        <span className="xs faint">Saved in this browser</span>
      </div>
    </div>
  );
}

function Row({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <div className="ns-row">
      <div className="ns-row-t"><b>{title}</b>{sub && <span>{sub}</span>}</div>
      {children}
    </div>
  );
}
