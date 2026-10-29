import { useEffect, useState } from "react";
import { useCompanies, useStartJob, useStatus } from "../lib/hooks";
import { useWatchlists, WatchList } from "../lib/live";
import { useScope } from "../lib/scope";
import { Icon, Popover } from "./ui";
import { useApp } from "./workbenchContext";
import { Select } from "./Select";

const LAST = "research.target.v1";
const ALL = "__all__";

/**
 * One button that starts a research run: on every covered company or on any
 * watchlist, as a quick sweep (news and market agents) or full research (all
 * 23 agents). `list` fixes the target (a watchlist's own page); otherwise the
 * list the app is focused on, or the last one used, is preselected.
 */
export function ResearchLauncher({ list, secondary, small }: { list?: WatchList; secondary?: boolean; small?: boolean }) {
  const lib = useWatchlists();
  const companies = useCompanies();
  const scope = useScope();
  const status = useStatus();
  const start = useStartJob();
  const app = useApp();
  const lists = (lib.data?.lists ?? []).filter((l) => l.count > 0);
  const [target, setTarget] = useState<string>(() => { try { return localStorage.getItem(LAST) || ALL; } catch { return ALL; } });
  const [quick, setQuick] = useState(true);
  useEffect(() => { if (scope.list && !list) setTarget(scope.list.id); }, [scope.list, list]);
  const chosen = list ?? lists.find((l) => l.id === target) ?? null;
  const covered = (companies.data ?? []).length;
  const busy = !!status.data?.active_job || start.isPending;
  const go = (close: () => void) => {
    try { if (!list) localStorage.setItem(LAST, chosen ? chosen.id : ALL); } catch { /* ignore */ }
    start.mutate({ kind: "agents", options: { quick, ...(chosen ? { watchlist: chosen.id } : {}) } }, {
      onSuccess: (j) => { close(); app.toast(`${quick ? "Quick sweep" : "Full research"} started on ${chosen ? `“${chosen.name}”` : "every covered company"}`, "ok"); app.showJob(j.id); },
      onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
    });
  };
  return (
    <Popover className="pop rl-pop" trigger={(open, toggle) => (
      <button className={`btn ${secondary ? "sec" : ""} ${small ? "sm" : ""} ${open ? "on" : ""}`} onClick={toggle} disabled={busy && !open}
        title={busy ? "A run is in progress - it can be followed from the Runs button at the top" : list ? `Research the ${list.count} companies on “${list.name}”` : "Start a research run on every company or on a watchlist"}>
        <Icon name="rocket" className="sm" />{list ? "Research this list" : "Research"}<Icon name="chevron-down" className="xs" />
      </button>
    )}>
      {(close) => (
        <div className="rl">
          <div className="label">Research</div>
          {!list && (
            <label className="fld"><span>Companies</span>
              <Select value={chosen ? chosen.id : ALL} onChange={setTarget} style={{ width: "100%" }}
                options={[{ value: ALL, label: "Every covered company", hint: covered, icon: "table" },
                  ...lists.map((l) => ({ value: l.id, label: l.name, hint: l.count, icon: "eye", group: "A watchlist" }))]} />
            </label>
          )}
          <div className="fld"><span>Depth</span>
            <div className="rl-depth">
              <button className={quick ? "on" : ""} onClick={() => setQuick(true)} aria-pressed={quick}><b><Icon name="zap" className="xs" />Quick sweep</b><span>News and market agents · minutes</span></button>
              <button className={!quick ? "on" : ""} onClick={() => setQuick(false)} aria-pressed={!quick}><b><Icon name="rocket" className="xs" />Full research</b><span>All 23 agents · longer</span></button>
            </div>
          </div>
          <button className="btn" onClick={() => go(close)} disabled={busy}>
            <Icon name={start.isPending ? "loading" : "play"} className={`sm ${start.isPending ? "spin" : ""}`} />
            Start on {chosen ? `“${chosen.name}” (${chosen.count})` : `all ${covered}`}
          </button>
          {busy && !start.isPending && <span className="xs faint">Another run is in progress — wait for it to finish.</span>}
        </div>
      )}
    </Popover>
  );
}
