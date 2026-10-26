import { Link } from "react-router-dom";
import { useScope } from "../lib/scope";
import { Icon, Popover } from "./ui";

/** Top bar: which watchlist the app is focused on. */
export function ScopePicker() {
  const s = useScope();
  return (
    <Popover className="menu scope-menu" trigger={(open, toggle) => (
      <button className={`scope-btn ${s.list ? "on" : ""} ${open ? "open" : ""}`} onClick={toggle} title="Focus the app on one watchlist" aria-haspopup="menu" aria-expanded={open}
        style={s.list ? { ["--wc" as string]: s.list.color } : undefined}>
        {s.list ? <i className="sw" /> : <Icon name="globe" className="sm" />}
        <span className="ellipsis">{s.label}</span>
        {s.list && <span className="n">{s.list.count}</span>}
        <Icon name="chevron-down" className="xs" />
      </button>
    )}>
      {(close) => (
        <div className="scope-list">
          <div className="label" style={{ padding: "6px 10px 4px" }}>Focus the app on</div>
          <button className={!s.list ? "on" : ""} onClick={() => { s.set(null); close(); }}>
            <Icon name="globe" className="sm" /><span className="grow">All companies</span>{!s.list && <Icon name="check" className="xs" />}
          </button>
          {s.lists.map((l) => (
            <button key={l.id} className={s.id === l.id ? "on" : ""} onClick={() => { s.set(l.id); close(); }} style={{ ["--wc" as string]: l.color }}>
              <i className="sw" /><span className="grow ellipsis">{l.name}</span><span className="xs faint">{l.count}</span>{s.id === l.id && <Icon name="check" className="xs" />}
            </button>
          ))}
          <hr />
          <Link to="/watchlist" className="scope-manage" onClick={close}><Icon name="library" className="sm" />Manage watchlists</Link>
          <span className="xs faint" style={{ padding: "4px 10px 6px", display: "block", lineHeight: 1.4 }}>Coverage, the Command Center, Universe, Model Performance and the research workforce show only the chosen list's companies.</span>
        </div>
      )}
    </Popover>
  );
}

/** A thin line on a scoped page: what it is showing, and a way back to everything. */
export function ScopeNote({ shown, total, what = "companies" }: { shown?: number; total?: number; what?: string }) {
  const s = useScope();
  if (!s.list) return null;
  return (
    <div className="scope-note" style={{ ["--wc" as string]: s.list.color }}>
      <i className="sw" /><span>Focused on <b>{s.list.name}</b>{shown != null && total != null ? ` · ${shown} of ${total} ${what}` : ""}</span>
      <span className="spacer" />
      <Link to={`/watchlist/${encodeURIComponent(s.list.id)}`} className="xs">Open the list</Link>
      <button className="btn xs ghost" onClick={() => s.set(null)}><Icon name="close" className="xs" />Show all</button>
    </div>
  );
}
