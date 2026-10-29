import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWatchlistMutations, useWatchlists, useWatchMutations, WatchItem, WatchList } from "../lib/live";
import { isNum, num, when } from "../lib/format";
import { Icon } from "./ui";
import { useApp } from "./workbenchContext";
import { ActionMenu } from "./Select";

/** A watched company's price alerts, note and lists - the watchlist side panel shows both parts together. */
export function WatchControls({ w, list, onRemoved }: { w: WatchItem; list?: WatchList | null; onRemoved?: () => void }) {
  return (
    <div className="wl-form">
      <PriceAlerts w={w} />
      <NoteBox w={w} list={list} onRemoved={onRemoved} />
    </div>
  );
}

const err = (app: ReturnType<typeof useApp>) => (e: unknown) => app.toast(e instanceof Error ? e.message : String(e), "error");

/** Alert levels: one row of two prices and Save (under the chart on a company's page). */
export function PriceAlerts({ w, row }: { w: WatchItem; row?: boolean }) {
  const m = useWatchMutations();
  const app = useApp();
  const [below, setBelow] = useState(w.alert_below?.toString() ?? "");
  const [above, setAbove] = useState(w.alert_above?.toString() ?? "");
  useEffect(() => { setBelow(w.alert_below?.toString() ?? ""); setAbove(w.alert_above?.toString() ?? ""); }, [w.ticker, w.alert_below, w.alert_above]);
  const dirty = below !== (w.alert_below?.toString() ?? "") || above !== (w.alert_above?.toString() ?? "");
  const save = () => m.update.mutate({ ticker: w.ticker, alert_below: below || null, alert_above: above || null }, { onSuccess: () => app.toast("Price alerts saved", "ok"), onError: err(app) });
  const last = w.quote?.last;
  return (
    <div className={`pa ${row ? "row-form" : ""}`}>
      <div className="label">Price alerts</div>
      <div className="pa-f">
        <label className="fld"><span>Alert when at or below</span><input className="inp sm num" inputMode="decimal" value={below} placeholder={isNum(last) ? num(last * 0.95, 0) : "price"} onChange={(e) => setBelow(e.target.value.replace(/[^\d.]/g, ""))} onKeyDown={(e) => e.key === "Enter" && dirty && save()} /></label>
        <label className="fld"><span>Alert when at or above</span><input className="inp sm num" inputMode="decimal" value={above} placeholder={isNum(last) ? num(last * 1.05, 0) : "price"} onChange={(e) => setAbove(e.target.value.replace(/[^\d.]/g, ""))} onKeyDown={(e) => e.key === "Enter" && dirty && save()} /></label>
        {row && <button className="btn sm" disabled={!dirty || m.update.isPending} onClick={save}>Save alerts</button>}
      </div>
      <span className="xs faint">Also alerted automatically when the price falls below the HYBRID MODEL buy-below, or moves more than the daily-move limit.</span>
      {!row && <div className="row"><button className="btn sm" disabled={!dirty || m.update.isPending} onClick={save}>Save alerts</button></div>}
    </div>
  );
}

/** Why you watch it, which lists it is on, and taking it off this one. */
export function NoteBox({ w, list, onRemoved, titled }: { w: WatchItem; list?: WatchList | null; onRemoved?: () => void; titled?: boolean }) {
  const m = useWatchMutations();
  const app = useApp();
  const [note, setNote] = useState(w.note ?? "");
  useEffect(() => { setNote(w.note ?? ""); }, [w.ticker, w.note]);
  const dirty = note !== (w.note ?? "");
  const save = () => m.update.mutate({ ticker: w.ticker, note }, { onSuccess: () => app.toast("Note saved", "ok"), onError: err(app) });
  return (
    <div className="nb">
      <label className="fld">{!titled && <span>Note</span>}<textarea className="inp" rows={4} aria-label="Note" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="Why you are watching it"
        onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && dirty) save(); }} /></label>
      <div className="row">
        <button className="btn sm" disabled={!dirty || m.update.isPending} onClick={save}>Save</button>
        <span className="spacer" />
        {list && <button className="btn sm ghost" onClick={() => { if (confirm(`Take ${w.name} off “${list.name}”?${(w.lists?.length ?? 1) > 1 ? " It stays on your other lists." : " Its stored minute bars are kept."}`)) m.remove.mutate({ ticker: w.ticker, list: list.id }, { onSuccess: onRemoved }); }}><Icon name="trash" className="xs" />Remove from list</button>}
      </div>
      <OnLists w={w} current={list?.id} />
      <div className="xs faint">Added {when(w.added)}{isNum(w.added_price) ? ` at ${num(w.added_price)}` : ""} · {w.sector}</div>
    </div>
  );
}

/** The lists a company is on (chips that open them), and "Add to another list". */
function OnLists({ w, current }: { w: WatchItem; current?: string }) {
  const lib = useWatchlists();
  const nav = useNavigate();
  const on = (lib.data?.lists ?? []).filter((l) => (w.lists ?? []).includes(l.id) && l.id !== current);
  return (
    <div className="row xs" style={{ gap: 4, flexWrap: "wrap" }}>
      {on.length > 0 && <span className="faint">{current ? "Also on" : "On"}</span>}
      {on.map((l) => <button key={l.id} className="wl-chip" style={{ ["--wc" as string]: l.color }} onClick={() => nav(`/watchlist/${encodeURIComponent(l.id)}`)}><i />{l.name}</button>)}
      <AddToList company={w} except={w.lists ?? []} small />
    </div>
  );
}

/** "Add to watchlist": any list the company is not on yet. */
export function AddToList({ company, except = [], small }: { company: { ticker: string; name?: string; sector?: string }; except?: string[]; small?: boolean }) {
  const lib = useWatchlists();
  const lm = useWatchlistMutations();
  const app = useApp();
  const lists = (lib.data?.lists ?? []).filter((l) => !except.includes(l.id));
  if (!lists.length) return null;
  return (
    <ActionMenu small={small} label={small ? "Add to list" : "Add to watchlist"} icon="add" disabled={lm.addMany.isPending}
      items={lists.map((l) => ({ label: l.name, hint: l.count, onClick: () => lm.addMany.mutate({ id: l.id, tickers: [company] }, {
        onSuccess: () => app.toast(`${company.name ?? company.ticker} added to “${l.name}”`, "ok"), onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
      }) }))} />
  );
}
