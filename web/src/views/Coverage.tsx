import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useIntel } from "../lib/hooks";
import { Verdict } from "../lib/api";
import { isNum, isoWhen, money, pct, shortName, signed, slug } from "../lib/format";
import { HM_COLOR, LABELS, LABEL_HEX, LEAD_SHORT, LENSES, LENS_COLOR, LENS_NAME, scoreColor } from "../lib/labels";
import { Diverge, Empty, Icon, LabelBadge, Meter, PageHeader, Panel, QueryView, RangeBar } from "../components/ui";
import { Column, DataGrid, GridTools, useGridState } from "../components/DataGrid";
import { RunButton } from "../components/RunButton";
import { ExportButton } from "../components/ExportButton";
import { useScope } from "../lib/scope";
import { ScopeNote } from "../components/ScopePicker";

const EXPORT_TITLE = "Coverage";

export function Coverage() {
  const q = useIntel();
  const scope = useScope();
  return (
    <div className="page fill">
      <QueryView q={q} rows={14}>
        {(d) =>
          !d.available || !d.verdicts.length ? (
            <>
              <PageHeader crumbs={[{ label: "Analysis" }, { label: "Coverage" }]} title="Coverage" />
              <Panel><Empty icon="table" title="No research yet" action={<RunButton kind="agents" label="Run research" icon="rocket" />}>
                Every company gets a HYBRID MODEL value with its range, confidence, red flags and the evidence behind each finding.
              </Empty></Panel>
            </>
          ) : scope.list && !d.verdicts.some((v) => scope.has({ ticker: v.ticker, company: v.company })) ? (
            <>
              <PageHeader crumbs={[{ label: "Analysis" }, { label: "Coverage" }]} title="Coverage" />
              <ScopeNote shown={0} total={d.verdicts.length} />
              <Panel><Empty icon="library" title={`No company on “${scope.list.name}” has been researched yet`} action={<button className="btn sec" onClick={() => scope.set(null)}>Show every company</button>}>
                Open the list and use <b>Research this list</b>, or run research on the whole universe.
              </Empty></Panel>
            </>
          ) : <Grid verdicts={scope.list ? d.verdicts.filter((v) => scope.has({ ticker: v.ticker, company: v.company })) : d.verdicts} total={d.verdicts.length} sub={`Run #${d.meta?.run_id} · ${d.meta?.mode} · ${isoWhen(d.meta?.started)}`} />
        }
      </QueryView>
    </div>
  );
}

function Grid({ verdicts, total, sub }: { verdicts: Verdict[]; total: number; sub: string }) {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState("");
  const [labels, setLabels] = useState<Set<string>>(new Set());
  const [sector, setSector] = useState("");
  const selected = params.get("sel");
  const setSel = (k: string | null) => { const p = new URLSearchParams(params); if (k) p.set("sel", k); else p.delete("sel"); setParams(p, { replace: true }); };
  const sectors = useMemo(() => [...new Set(verdicts.map((v) => v.sector))].sort(), [verdicts]);
  const rows = useMemo(() => {
    const t = text.trim().toLowerCase();
    return verdicts.filter((v) => (!t || v.company.toLowerCase().includes(t) || (v.ticker ?? "").toLowerCase().includes(t)) && (!labels.size || labels.has(v.label)) && (!sector || v.sector === sector));
  }, [verdicts, text, labels, sector]);
  const scale = useMemo(() => {
    // each row's range bar is drawn relative to its own price
    return (v: Verdict) => {
      const pts = [v.low, v.high, v.bear_value, v.bull_value, v.price, v.expected_value].filter(isNum) as number[];
      return pts.length ? { min: Math.min(...pts) * 0.95, max: Math.max(...pts) * 1.05 } : { min: 0, max: 1 };
    };
  }, []);

  const columns: Column<Verdict>[] = [
    { key: "company", header: "Company", sticky: true, fixed: true, sort: (v) => v.company, render: (v) => <div className="co"><b>{shortName(v.company)}</b><small>{v.ticker}</small></div> },
    { key: "sector", header: "Sector", sort: (v) => v.sector, render: (v) => <span className="muted ellipsis" style={{ maxWidth: 190, display: "inline-block" }}>{v.sector}</span> },
    { key: "label", header: "Label", sort: (v) => LABELS.indexOf(v.label as (typeof LABELS)[number]), exportValue: (v) => v.label, render: (v) => <LabelBadge label={v.label} /> },
    { key: "price", header: "Price", align: "r", sort: (v) => v.price, render: (v) => <span className="mono">{money(v.price)}</span> },
    { key: "value", header: "HYBRID MODEL", align: "r", sort: (v) => v.expected_value, render: (v) => <span className="mono strong">{money(v.expected_value)}</span> },
    { key: "range", header: "Range · value · price", render: (v) => { const s = scale(v); return <RangeBar low={v.low ?? v.bear_value} high={v.high ?? v.bull_value} value={v.expected_value} price={v.price} min={s.min} max={s.max} />; } },
    { key: "upside", header: "Upside", align: "r", sort: (v) => v.upside, exportValue: (v) => pct(v.upside, 1, true), render: (v) => <span className={`mono ${isNum(v.upside) ? (v.upside >= 0 ? "up" : "down") : ""}`}>{pct(v.upside, 1, true)}</span> },
    { key: "buy", header: "Buy-below", align: "r", sort: (v) => v.buy_below, render: (v) => <span className="mono muted">{money(v.buy_below)}</span> },
    { key: "conf", header: "Confidence", sort: (v) => v.confidence, exportValue: (v) => (isNum(v.confidence) ? v.confidence.toFixed(0) : ""), render: (v) => <div className="row"><Meter value={v.confidence} width={52} /><span className="mono muted">{isNum(v.confidence) ? v.confidence.toFixed(0) : "—"}</span></div> },
    { key: "score", header: "Research", sort: (v) => v.research_score, exportValue: (v) => signed(v.research_score), render: (v) => <div className="row"><Diverge value={v.research_score} width={60} /><span className="mono muted">{signed(v.research_score)}</span></div> },
    { key: "flags", header: "Flags", align: "r", sort: (v) => v.red_flags?.length ?? 0, render: (v) => <span className={`mono ${(v.red_flags?.length ?? 0) ? "down" : "faint"}`}>{v.red_flags?.length ?? 0}</span> },
    { key: "regime", header: "Type", visible: false, sort: (v) => v.regime ?? "", render: (v) => <span className="muted">{v.regime ?? "—"}</span> },
    { key: "k", header: "Cost of equity", align: "r", visible: false, sort: (v) => v.cost_of_equity, render: (v) => <span className="mono">{pct(v.cost_of_equity, 1)}</span> },
    { key: "g", header: "Growth", align: "r", visible: false, sort: (v) => v.growth, render: (v) => <span className="mono">{pct(v.growth, 1)}</span> },
  ];
  const state = useGridState<Verdict>("coverage", columns, { key: "upside", asc: false });
  const sel = verdicts.find((v) => v.company === selected) ?? null;

  const exportTable = () => ({
    head: ["Company", "Ticker", "Sector", "Label", "Price", "HYBRID MODEL", "Low", "High", "Upside", "Buy-below", "Confidence", "Red flags"],
    rows: rows.map((v) => [v.company, v.ticker, v.sector, v.label, v.price, v.expected_value, v.low, v.high, v.upside, v.buy_below, v.confidence, (v.red_flags ?? []).join(" | ")]),
    subtitle: sub,
  });

  return (
    <>
      <PageHeader crumbs={[{ label: "Analysis" }, { label: "Coverage" }]} title="Coverage" sub={sub}
        actions={<><ExportButton title="Coverage" table={exportTable} label="Export data" className="btn sec" /><RunButton kind="agents" options={{ quick: true }} label="Quick sweep" icon="zap" secondary /><RunButton kind="agents" label="Run research" icon="rocket" /></>} />
      <ScopeNote shown={verdicts.length} total={total} />
      <div className={`split ${sel ? "" : "closed"}`}>
        <section className="panel" style={{ minHeight: 0 }}>
          <div className="toolbar">
            <div className="search" style={{ width: 240 }}><Icon name="search" /><input value={text} onChange={(e) => setText(e.target.value)} placeholder="Filter by company or ticker" /></div>
            <select className="sel" value={sector} onChange={(e) => setSector(e.target.value)}><option value="">All sectors</option>{sectors.map((s) => <option key={s}>{s}</option>)}</select>
            {LABELS.map((l) => {
              const n = verdicts.filter((v) => v.label === l).length;
              if (!n) return null;
              const on = labels.has(l);
              return <button key={l} className={`chip ${on ? "on" : ""}`} onClick={() => { const s = new Set(labels); if (on) s.delete(l); else s.add(l); setLabels(s); }}><span className="sw" style={{ background: LABEL_HEX[l] }} />{l}<span className="faint">{n}</span></button>;
            })}
            <span className="spacer" />
            <span className="faint xs">{rows.length} of {verdicts.length} · ↑↓ to move · Enter to open</span>
            <GridTools columns={columns} state={state} exportRows={rows} exportTitle={EXPORT_TITLE} />
          </div>
          <DataGrid rows={rows} columns={columns} rowKey={(v) => v.company} state={state} selected={selected}
            onSelect={setSel} onOpen={(k) => nav(`/coverage/${slug(k)}`)} empty="No company matches these filters." />
        </section>
        {sel && <Inspector v={sel} onClose={() => setSel(null)} />}
      </div>
    </>
  );
}

function Inspector({ v, onClose }: { v: Verdict; onClose: () => void }) {
  const lenses = v.lenses ?? {};
  const lv = LENSES.map((l) => lenses[l]).filter(isNum) as number[];
  const lmax = Math.max(1, ...lv, isNum(v.price) ? v.price : 0);
  return (
    <aside className="insp">
      <div className="insp-h">
        <div className="row">
          <div className="grow"><div className="strong" style={{ fontSize: 15 }}>{shortName(v.company)}</div><div className="faint xs mono">{v.ticker} · {v.sector}</div></div>
          <button className="ibtn" onClick={onClose} title="Close"><Icon name="close" /></button>
        </div>
        <div className="row" style={{ marginTop: 10 }}><LabelBadge label={v.label} />{v.regime && <span className="tag">{v.regime}</span>}<span className="tag hm">HYBRID MODEL</span></div>
      </div>
      <div className="insp-b">
        <div className="figs">
          <div><div className="k">Price</div><div className="v" style={{ color: "var(--price)" }}>{money(v.price)}</div></div>
          <div><div className="k">HYBRID MODEL</div><div className="v" style={{ color: HM_COLOR }}>{money(v.expected_value)}</div><div className={`s ${isNum(v.upside) ? (v.upside >= 0 ? "up" : "down") : ""}`}>{pct(v.upside, 1, true)}</div></div>
          <div><div className="k">Range P10–P90</div><div className="v" style={{ fontSize: 14 }}>{money(v.low, 0)} – {money(v.high, 0)}</div></div>
          <div><div className="k">Confidence</div><div className="v">{isNum(v.confidence) ? v.confidence.toFixed(0) : "—"}</div><div className="s">buy-below {money(v.buy_below, 0)}</div></div>
        </div>
        {lv.length > 0 && (
          <div>
            <div className="label" style={{ marginBottom: 8 }}>Lenses</div>
            {LENSES.map((l) => isNum(lenses[l]) ? (
              <div key={l} className="row" style={{ gap: 8, padding: "3px 0" }}>
                <span style={{ width: 100 }} className="small muted">{LENS_NAME[l]}</span>
                <div className="grow" style={{ position: "relative", height: 8 }}>
                  <div style={{ position: "absolute", left: 0, top: 1, bottom: 1, width: `${(lenses[l]! / lmax) * 100}%`, background: LENS_COLOR[l], opacity: v.lens_weights?.[l] ? 0.85 : 0.3, borderRadius: 2 }} />
                  {isNum(v.price) && <div style={{ position: "absolute", left: `${(v.price / lmax) * 100}%`, top: -2, bottom: -2, width: 2, background: "var(--price)" }} />}
                </div>
                <span className="mono xs" style={{ width: 64, textAlign: "right" }}>{money(lenses[l], 0)}</span>
              </div>
            ) : null)}
          </div>
        )}
        <div>
          <div className="label" style={{ marginBottom: 8 }}>Research leads</div>
          {(v.leads ?? []).map((l) => (
            <div key={l.lead} className="row" style={{ padding: "3px 0" }}>
              <span className="small" style={{ width: 130 }}>{LEAD_SHORT[l.lead] ?? l.name}</span>
              <Diverge value={l.score} width="100%" />
              <span className="mono xs" style={{ width: 44, textAlign: "right", color: scoreColor(l.score) }}>{signed(l.score)}</span>
            </div>
          ))}
        </div>
        {(v.red_flags?.length ?? 0) > 0 && (
          <div>
            <div className="label" style={{ marginBottom: 6 }}>Red flags</div>
            <div className="list">{v.red_flags.map((f, i) => <div key={i} className="li"><Icon name="warning" className="sm down" /><span>{f}</span></div>)}</div>
          </div>
        )}
        {v.summary?.headline && <div><div className="label" style={{ marginBottom: 6 }}>Research note</div><p className="small" style={{ lineHeight: 1.6 }}>{v.summary.headline}</p></div>}
        <div className="row" style={{ marginTop: "auto" }}>
          <Link className="btn grow" to={`/coverage/${slug(v.company)}`}><Icon name="go-to-file" className="sm" />Open profile</Link>
          <Link className="btn sec" to={`/studio?company=${slug(v.company)}`}><Icon name="beaker" className="sm" />Studio</Link>
        </div>
      </div>
    </aside>
  );
}
