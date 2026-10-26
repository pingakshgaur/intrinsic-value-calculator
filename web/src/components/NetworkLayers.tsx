import { useState } from "react";
import { Kind, KIND_META, Roster } from "../lib/agents";
import { DEFAULT_LAYERS, EDGE_NAME, EdgeKind, Layers, PRESETS, View } from "../lib/netPrefs";
import { Icon, Popover, Toggle } from "./ui";

const PACKET_KINDS: Kind[] = ["fetch", "share", "finding", "flag", "request", "reply", "review", "summary", "verdict", "task"];
export const EDGE_COLOR: Record<EdgeKind, string> = { input: "#57a3f8", report: "#86cf86", command: "#ad80d7", consume: "#f0a35e", output: "#e0b97f", ops: "#9a9b9c" };

/** Everything the map can show, switched on and off in one place. */
export function LayersMenu({ layers, setLayers, roster, teamsOff, setTeamsOff, hidden, setHidden, kindsOff, setKindsOff, annotations, clearAnnotations, titleOf }: {
  layers: Layers; setLayers: (l: Layers) => void; roster: Roster;
  teamsOff: string[]; setTeamsOff: (t: string[]) => void;
  hidden: string[]; setHidden: (h: string[]) => void;
  kindsOff: Kind[]; setKindsOff: (k: Kind[]) => void;
  annotations: number; clearAnnotations: () => void;
  titleOf: (id: string) => string;
}) {
  const set = <K extends keyof Layers>(k: K, v: Layers[K]) => setLayers({ ...layers, [k]: v });
  const off = Object.values(layers.edges).filter((v) => !v).length + teamsOff.length + hidden.length;
  return (
    <Popover className="pop net-pop" trigger={(open, toggle) => (
      <button className={`net-btn ${open ? "on" : ""}`} onClick={toggle} title="Layers: choose what the map shows">
        <Icon name="layers" className="sm" />Layers{off > 0 && <span className="net-badge">{off} off</span>}<Icon name="chevron-down" className="xs" />
      </button>
    )}>
      {() => (
        <div className="nl">
          <section>
            <div className="nl-h">Arrangement</div>
            <div className="seg">
              <button className={layers.arrange === "hierarchy" ? "on" : ""} onClick={() => set("arrange", "hierarchy")}><Icon name="list-tree" className="xs" />Hierarchy</button>
              <button className={layers.arrange === "radial" ? "on" : ""} onClick={() => set("arrange", "radial")}><Icon name="target" className="xs" />Radial</button>
            </div>
            <div className="seg">
              <button className={layers.detail === "compact" ? "on" : ""} onClick={() => set("detail", "compact")}>Compact cards</button>
              <button className={layers.detail === "full" ? "on" : ""} onClick={() => set("detail", "full")}>Full cards</button>
            </div>
          </section>
          <section>
            <div className="nl-h">Nodes</div>
            <Toggle checked={layers.analysts} onChange={(v) => set("analysts", v)} label="Analysts (off = leads only)" />
            <Toggle checked={layers.sources} onChange={(v) => set("sources", v)} label="Data sources" />
            <Toggle checked={layers.outputs} onChange={(v) => set("outputs", v)} label="Outputs (verdicts, alerts, room)" />
            <Toggle checked={layers.ops} onChange={(v) => set("ops", v)} label="Run orchestrator" />
            {layers.arrange === "hierarchy" && <Toggle checked={layers.frames} onChange={(v) => set("frames", v)} label="Team bands" />}
          </section>
          <section>
            <div className="nl-h">Teams <span className="faint">click to hide</span></div>
            <div className="nl-chips">
              {Object.entries(roster.teams).filter(([c]) => c !== "OPS" && c !== "CMD").map(([code, t]) => (
                <button key={code} className={`chip ${teamsOff.includes(code) ? "" : "on"}`} onClick={() => setTeamsOff(teamsOff.includes(code) ? teamsOff.filter((x) => x !== code) : [...teamsOff, code])}>
                  <span className="sw" style={{ background: t.color }} />{code}
                </button>
              ))}
            </div>
          </section>
          <section>
            <div className="nl-h">Connections</div>
            {(Object.keys(EDGE_NAME) as EdgeKind[]).map((k) => (
              <Toggle key={k} checked={layers.edges[k]} onChange={(v) => set("edges", { ...layers.edges, [k]: v })}
                label={<span className="nl-edge"><i style={{ background: EDGE_COLOR[k] }} className={k === "input" ? "dot" : k === "consume" ? "dash" : ""} />{EDGE_NAME[k]}</span>} />
            ))}
            <Toggle checked={layers.labels} onChange={(v) => set("labels", v)} label="Edge captions" />
          </section>
          <section>
            <div className="nl-h">Motion</div>
            <Toggle checked={layers.packets} onChange={(v) => set("packets", v)} label="Info-bits travelling the edges" />
            <Toggle checked={layers.floats} onChange={(v) => set("floats", v)} label="Score pop-ups over agents" />
            {layers.packets && (
              <div className="nl-kinds">
                {PACKET_KINDS.map((k) => (
                  <button key={k} className={kindsOff.includes(k) ? "off" : ""} onClick={() => setKindsOff(kindsOff.includes(k) ? kindsOff.filter((x) => x !== k) : [...kindsOff, k])}>
                    <i style={{ background: KIND_META[k].color }} />{KIND_META[k].label}
                  </button>
                ))}
              </div>
            )}
          </section>
          <section>
            <div className="nl-h">Map</div>
            <Toggle checked={layers.minimap} onChange={(v) => set("minimap", v)} label="Mini-map" />
            <Toggle checked={layers.annotations} onChange={(v) => set("annotations", v)} label={`Your links and notes (${annotations})`} />
            {annotations > 0 && <button className="btn xs ghost" onClick={() => { if (confirm(`Delete all ${annotations} of your links and notes?`)) clearAnnotations(); }}><Icon name="trash" className="xs" />Clear links and notes</button>}
          </section>
          {hidden.length > 0 && (
            <section>
              <div className="nl-h">Hidden <button className="btn xs ghost" onClick={() => setHidden([])}>Show all</button></div>
              {hidden.map((id) => (
                <div key={id} className="nl-hidden"><span className="ellipsis">{id.startsWith("E:") ? `edge ${id.slice(2).replace(">", " → ")}` : `${id} · ${titleOf(id)}`}</span>
                  <button className="ibtn sm" title="Show" onClick={() => setHidden(hidden.filter((x) => x !== id))}><Icon name="eye" className="xs" /></button></div>
              ))}
            </section>
          )}
          <button className="btn xs ghost" onClick={() => { setLayers(DEFAULT_LAYERS); setTeamsOff([]); setHidden([]); setKindsOff([]); }}><Icon name="discard" className="xs" />Back to the simple view</button>
        </div>
      )}
    </Popover>
  );
}

/** Built-in views and the ones you saved. */
export function ViewsMenu({ views, setViews, current, apply }: { views: View[]; setViews: (v: View[]) => void; current: Omit<View, "name">; apply: (v: View) => void }) {
  const [name, setName] = useState("");
  return (
    <Popover className="pop net-pop sm" trigger={(open, toggle) => (
      <button className={`net-btn ${open ? "on" : ""}`} onClick={toggle} title="Views: saved arrangements of the map"><Icon name="bookmark" className="sm" />Views<Icon name="chevron-down" className="xs" /></button>
    )}>
      {(close) => (
        <div className="nl">
          <section>
            <div className="nl-h">Built in</div>
            {PRESETS.map((v) => <button key={v.name} className="nl-view" onClick={() => { apply(v); close(); }}><Icon name="eye" className="xs" />{v.name}</button>)}
          </section>
          <section>
            <div className="nl-h">Yours</div>
            {views.length === 0 && <span className="xs faint">Arrange the map, then save it here.</span>}
            {views.map((v) => (
              <div key={v.name} className="nl-hidden">
                <button className="nl-view grow" onClick={() => { apply(v); close(); }}><Icon name="bookmark" className="xs" />{v.name}</button>
                <button className="ibtn sm" title="Delete" onClick={() => setViews(views.filter((x) => x.name !== v.name))}><Icon name="trash" className="xs" /></button>
              </div>
            ))}
            <div className="row" style={{ gap: 6 }}>
              <input className="inp sm grow" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name this view" onKeyDown={(e) => e.stopPropagation()} />
              <button className="btn xs" disabled={!name.trim()} onClick={() => { setViews([...views.filter((x) => x.name !== name.trim()), { name: name.trim(), ...current }]); setName(""); }}>Save</button>
            </div>
          </section>
        </div>
      )}
    </Popover>
  );
}
