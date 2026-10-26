import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useIntel, useLabCompanies, useStartJob } from "../lib/hooks";
import { shortName, slug } from "../lib/format";
import { Icon } from "./ui";
import { useApp } from "./workbenchContext";
import { loadTour } from "./Tour";
import { CHAPTERS } from "../lib/tourSteps";

interface Cmd {
  id: string;
  group: string;
  label: string;
  icon: string;
  hint?: string;
  /** extra words it is found by, not shown */
  keys?: string;
  run: () => void;
}

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const intel = useIntel();
  const lab = useLabCompanies();
  const start = useStartJob();
  const app = useApp();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => input.current?.focus(), []);

  const commands = useMemo<Cmd[]>(() => {
    const go = (path: string) => () => nav(path);
    const job = (kind: string, options: Record<string, unknown> = {}) => () =>
      start.mutate(
        { kind, options },
        { onSuccess: (j) => app.showJob(j.id), onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error") },
      );
    const saved = loadTour();
    const TOUR = "onboarding tour welcome guide intro help walkthrough";
    const c: Cmd[] = [
      { id: "t-start", group: "Start here", label: "Onboarding · guided tour of INTVAL Workbench", icon: "compass", hint: "tour", keys: TOUR, run: () => app.startTour() },
      ...(saved && !saved.finished && saved.idx > 0 ? [{ id: "t-resume", group: "Start here", label: `Resume onboarding (step ${saved.idx + 1})`, icon: "debug-continue", keys: TOUR, run: () => app.startTour({ resume: true }) }] : []),
      ...CHAPTERS.map((ch, i) => ({ id: `t-${ch.id}`, group: "Onboarding chapters", label: `Onboarding · ${ch.title}`, icon: ch.icon, hint: `${ch.steps.length} steps`, keys: `${TOUR} ${ch.blurb}`, run: () => app.startTour({ chapter: i }) })),
      { id: "p-o", group: "Go to", label: "Command Center", icon: "pulse", hint: "Alt+1", run: go("/") },
      { id: "p-mk", group: "Go to", label: "Markets · live scanner and charts", icon: "graph", hint: "Alt+2", run: go("/markets") },
      { id: "p-wl", group: "Go to", label: "Watchlists · your lists, tracked live", icon: "eye", hint: "Alt+3", run: go("/watchlist") },
      { id: "p-r", group: "Go to", label: "Coverage", icon: "table", hint: "Alt+4", run: go("/coverage") },
      { id: "p-agents", group: "Go to", label: "Research workforce · overview of the agents and runs", icon: "organization", run: go("/agents") },
      { id: "p-net", group: "Go to", label: "Agent Network · live graph of the 23 agents", icon: "type-hierarchy", run: go("/agents/network") },
      { id: "p-room", group: "Go to", label: "Research Room · agent chat", icon: "comment-discussion", run: go("/agents/chat") },
      { id: "p-l", group: "Go to", label: "HYBRID MODEL Studio", icon: "beaker", hint: "Alt+5", run: go("/studio") },
      { id: "p-m", group: "Go to", label: "Model Performance", icon: "graph-line", hint: "Alt+6", run: go("/performance") },
      { id: "p-le", group: "Go to", label: "Learning data", icon: "mortar-board", hint: "Alt+7", run: go("/learning") },
      { id: "p-u", group: "Go to", label: "Universe", icon: "database", hint: "Alt+8", run: go("/universe") },
      { id: "p-run", group: "Go to", label: "Operations", icon: "server-process", hint: "Alt+9", run: go("/operations") },
      { id: "p-s", group: "Go to", label: "Configuration", icon: "settings", run: go("/configuration") },
      { id: "r-learn", group: "Run", label: "Fetch learning data (training lists + watchlist)", icon: "cloud-download", run: job("learn") },
      { id: "r-retrain", group: "Run", label: "Fetch learning data and retrain", icon: "sync", run: job("learn", { retrain: true }) },
      { id: "p-ai", group: "Go to", label: "Configuration · AI providers", icon: "sparkle", run: go("/configuration?section=ai") },
      { id: "p-help", group: "Go to", label: "Glossary", icon: "book", hint: "?", run: app.openHelp },
      { id: "r-full", group: "Run", label: "Full research (23 agents)", icon: "rocket", run: job("agents") },
      { id: "r-quick", group: "Run", label: "Quick news & market sweep", icon: "zap", run: job("agents", { quick: true }) },
      { id: "r-val", group: "Run", label: "Valuation report (all models)", icon: "graph", run: job("valuation") },
      { id: "r-screen", group: "Run", label: "Data sufficiency check", icon: "filter", run: job("screen") },
      { id: "r-llm", group: "Run", label: "Check AI keys and models", icon: "plug", run: job("llm_check") },
    ];
    const seen = new Set<string>();
    for (const v of intel.data?.verdicts ?? []) {
      seen.add(v.company);
      c.push({ id: "c-" + v.company, group: "Companies", label: shortName(v.company), icon: "symbol-class", hint: v.label, run: go(`/coverage/${slug(v.company)}`) });
      c.push({ id: "l-" + v.company, group: "Open in Studio", label: shortName(v.company), icon: "beaker", run: go(`/studio?company=${slug(v.company)}`) });
      if (v.ticker) c.push({ id: "k-" + v.company, group: "Live chart", label: shortName(v.company), icon: "graph", hint: v.ticker, run: go(`/markets?t=${encodeURIComponent(v.ticker)}`) });
    }
    for (const r of lab.data ?? []) {
      if (seen.has(r.company)) continue;
      c.push({ id: "l-" + r.company, group: "Open in Studio", label: shortName(r.company), icon: "beaker", hint: "report inputs", run: go(`/studio?company=${slug(r.company)}`) });
    }
    return c;
  }, [intel.data, lab.data, nav, start, app]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return commands.filter((c) => c.group === "Start here" || c.group === "Go to" || c.group === "Run");
    const words = s.split(/\s+/);
    return commands.filter((c) => words.every((w) => (c.label + " " + c.group + " " + (c.hint ?? "") + " " + (c.keys ?? "")).toLowerCase().includes(w))).slice(0, 60);
  }, [q, commands]);

  useEffect(() => setSel(0), [q]);
  useEffect(() => {
    list.current?.querySelector(".palette-item.on")?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  const exec = (c: Cmd | undefined) => {
    if (!c) return;
    onClose();
    c.run();
  };

  let lastGroup = "";
  return (
    <>
      <div className="palette-scrim" onMouseDown={onClose} />
      <div className="palette" role="dialog" aria-label="Search">
        <div className="palette-input">
          <Icon name="search" />
          <input
            ref={input}
            value={q}
            placeholder="Search companies, pages and actions…"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setSel((s) => Math.min(filtered.length - 1, s + 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSel((s) => Math.max(0, s - 1));
              } else if (e.key === "Enter") exec(filtered[sel]);
              else if (e.key === "Escape") onClose();
            }}
          />
          <kbd>Esc</kbd>
        </div>
        <div className="palette-list" ref={list}>
          {filtered.length === 0 && <div className="palette-group">Nothing matches “{q}”</div>}
          {filtered.map((c, i) => {
            const head = c.group !== lastGroup ? <div className="palette-group">{c.group}</div> : null;
            lastGroup = c.group;
            return (
              <div key={c.id}>
                {head}
                <div className={`palette-item ${i === sel ? "on" : ""}`} onMouseEnter={() => setSel(i)} onMouseDown={() => exec(c)}>
                  <Icon name={c.icon} />
                  <span className="ellipsis">{c.label}</span>
                  {c.hint && <span className="hint">{c.hint}</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
