import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useIntel, useMetrics, useStatus, useValuation } from "../lib/hooks";
import { CsvRow, Verdict } from "../lib/api";
import { ago, isNum, isoWhen, pct, pctUnits, shortName, slug } from "../lib/format";
import { HM_COLOR, LABELS, LABEL_HEX } from "../lib/labels";
import { Icon, Loading, PageHeader, Panel } from "../components/ui";
import { RunButton } from "../components/RunButton";
import { CoverageMap, UpsideScatter } from "../components/charts";

function median(xs: number[]) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function CommandCenter() {
  const intel = useIntel();
  const val = useValuation();
  const metrics = useMetrics();
  const status = useStatus();
  const nav = useNavigate();
  if (intel.isLoading || val.isLoading) return <div className="page"><Loading rows={12} /></div>;

  const verdicts = intel.data?.verdicts ?? [];
  const meta = intel.data?.meta;
  const hasIntel = verdicts.length > 0;
  const hm = (metrics.data?.overall ?? []).find((r) => r.Model === "HYBRID MODEL");
  const open = (c: string) => nav(`/coverage/${slug(c)}`);

  return (
    <div className="page">
      <PageHeader
        crumbs={[{ label: "Analysis" }, { label: "Command Center" }]}
        title="Command Center"
        sub={hasIntel ? <>Research run #{meta?.run_id} · {meta?.mode} · {isoWhen(meta?.started)} · {meta?.llm_mode}</> : "Valuation and research across your coverage universe"}
        actions={<><RunButton kind="agents" options={{ quick: true }} label="Quick sweep" icon="zap" secondary /><RunButton kind="agents" label="Run research" icon="rocket" /></>}
      />

      <Band verdicts={verdicts} hm={hm} report={status.data?.valuation_updated ?? null} />

      {!hasIntel ? (
        <Panel title="Get started">
          <div className="grid c3">
            {[
              ["database", "1  Define the universe", "Companies, sectors and NSE tickers.", "/universe"],
              ["server-process", "2  Run valuation and research", "All models for every year, then the 23-agent research.", "/operations"],
              ["beaker", "3  Tune the HYBRID MODEL", "Change constants and see every value respond before you save.", "/studio"],
            ].map(([icon, t, d, to]) => (
              <Link key={t} to={to} className="jt" style={{ textDecoration: "none" }}>
                <b><Icon name={icon} className="sm" />{t}</b><span>{d}</span>
              </Link>
            ))}
          </div>
        </Panel>
      ) : (
        <>
          <div className="grid c-21">
            <Panel title="Coverage map" meta="tile size: market cap · colour: upside to HYBRID MODEL value"
              tools={<span className="scale">below value<span className="bar" />above value</span>} flush>
              <div style={{ padding: 10 }}><CoverageMap verdicts={verdicts} onPick={open} height={380} /></div>
            </Panel>
            <Signals verdicts={verdicts} problems={meta?.feed_problems ?? []} onPick={open} />
          </div>
          <div className="grid c2">
            <Panel title="Upside vs confidence" meta="dot size: red flags">
              <UpsideScatter verdicts={verdicts} onPick={open} height={300} />
            </Panel>
            <Distribution verdicts={verdicts} onPick={open} />
          </div>
        </>
      )}

      {val.data?.available && <Leaderboard rows={metrics.data?.overall ?? []} updated={metrics.data?.updated ?? null} />}
    </div>
  );
}

function Band({ verdicts, hm, report }: { verdicts: Verdict[]; hm?: CsvRow; report: number | null }) {
  const s = useMemo(() => {
    const ups = verdicts.map((v) => v.upside).filter(isNum) as number[];
    const conf = verdicts.map((v) => v.confidence).filter(isNum) as number[];
    return {
      cheap: verdicts.filter((v) => v.label === "Deep value" || v.label === "Undervalued").length,
      dear: verdicts.filter((v) => v.label === "Overvalued").length,
      flags: verdicts.reduce((a, v) => a + (v.red_flags?.length ?? 0), 0),
      med: median(ups),
      conf: conf.length ? conf.reduce((a, b) => a + b, 0) / conf.length : null,
    };
  }, [verdicts]);
  return (
    <div className="band">
      <div><div className="k"><Icon name="organization" className="xs" />Coverage</div><div className="v">{verdicts.length}</div><div className="s">companies researched</div></div>
      <div><div className="k"><Icon name="arrow-down" className="xs" />Below value</div><div className="v up">{s.cheap}</div><div className="s">deep value + undervalued</div></div>
      <div><div className="k"><Icon name="arrow-up" className="xs" />Above value</div><div className="v warn">{s.dear}</div><div className="s">overvalued</div></div>
      <div><div className="k"><Icon name="graph" className="xs" />Median upside</div><div className={`v ${isNum(s.med) ? (s.med >= 0 ? "up" : "down") : ""}`}>{pct(s.med, 1, true)}</div><div className="s">price → HYBRID MODEL</div></div>
      <div><div className="k"><Icon name="verified" className="xs" />Avg confidence</div><div className="v">{isNum(s.conf) ? s.conf.toFixed(0) : "—"}</div><div className="s">out of 100</div></div>
      <div><div className="k"><Icon name="warning" className="xs" />Red flags</div><div className={`v ${s.flags ? "down" : ""}`}>{s.flags}</div><div className="s">validated</div></div>
      <div><div className="k"><Icon name="target" className="xs" />HYBRID MODEL error</div><div className="v hm">{hm ? pctUnits(hm["MedAPE %"], 1) : "—"}</div><div className="s">median, back-test · {ago(report)}</div></div>
    </div>
  );
}

function Signals({ verdicts, problems, onPick }: { verdicts: Verdict[]; problems: string[]; onPick: (c: string) => void }) {
  const items = [
    ...verdicts.flatMap((v) => (v.red_flags ?? []).map((t) => ({ v, t, icon: "warning", cls: "down", kind: "Red flag" }))),
    ...verdicts.flatMap((v) => (v.changes ?? []).filter((c) => !c.startsWith("first")).map((t) => ({ v, t, icon: t.startsWith("label") ? "tag" : "pulse", cls: "info", kind: "Change" }))),
  ];
  return (
    <Panel title="Signals" meta={`${items.length} from the latest run`} flush>
      <div className="feed" style={{ maxHeight: 400, overflow: "auto" }}>
        {items.length === 0 && <div className="empty" style={{ padding: 32 }}><Icon name="pass" className="up" /><span className="small">No red flags or changes since the last run.</span></div>}
        {items.slice(0, 50).map((x, i) => (
          <div className="ev" key={i} onClick={() => onPick(x.v.company)}>
            <span className="ic"><Icon name={x.icon} className={`sm ${x.cls}`} /></span>
            <div style={{ minWidth: 0 }}><div className="t row"><span className="ellipsis">{shortName(x.v.company)}</span><span className="tag" style={{ marginLeft: "auto" }}>{x.kind}</span></div><div className="d">{x.t}</div></div>
          </div>
        ))}
        {problems.slice(0, 4).map((p, i) => (
          <div className="ev" key={"p" + i} style={{ cursor: "default" }}>
            <span className="ic"><Icon name="debug-disconnect" className="sm warn" /></span>
            <div><div className="t">Data source</div><div className="d">{p}</div></div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function Distribution({ verdicts, onPick }: { verdicts: Verdict[]; onPick: (c: string) => void }) {
  const ranked = [...verdicts].filter((v) => isNum(v.upside) && v.label !== "Insufficient evidence").sort((a, b) => (b.upside ?? 0) - (a.upside ?? 0));
  const extremes = [...ranked.slice(0, 4), ...ranked.slice(-4).filter((v) => !ranked.slice(0, 4).includes(v))];
  const total = verdicts.length || 1;
  return (
    <Panel title="Label mix and extremes" meta="price ÷ HYBRID MODEL value">
      <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", marginBottom: 10 }}>
        {LABELS.map((l) => {
          const n = verdicts.filter((v) => v.label === l).length;
          return n ? <div key={l} title={`${l}: ${n}`} style={{ width: `${(n / total) * 100}%`, background: LABEL_HEX[l] }} /> : null;
        })}
      </div>
      <div className="legend" style={{ marginBottom: 12 }}>
        {LABELS.map((l) => { const n = verdicts.filter((v) => v.label === l).length; return n ? <span key={l}><i style={{ background: LABEL_HEX[l] }} />{l} <b className="strong">{n}</b></span> : null; })}
      </div>
      <table className="dg dense">
        <thead><tr><th>Company</th><th>Sector</th><th className="r">Upside</th></tr></thead>
        <tbody>
          {extremes.map((v) => (
            <tr key={v.company} className="click" onClick={() => onPick(v.company)}>
              <td className="strong">{shortName(v.company)}</td><td className="muted ellipsis" style={{ maxWidth: 180 }}>{v.sector}</td>
              <td className={`r mono ${(v.upside ?? 0) >= 0 ? "up" : "down"}`}>{pct(v.upside, 1, true)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

export function Leaderboard({ rows, updated }: { rows: CsvRow[]; updated: number | null }) {
  const data = rows.filter((r) => isNum(r["MedAPE %"])).sort((a, b) => (a["MedAPE %"] as number) - (b["MedAPE %"] as number));
  if (!data.length) return null;
  const maxE = Math.max(...data.map((r) => r["MedAPE %"] as number));
  return (
    <Panel title="Model leaderboard" meta={`back-test against the 1-May price · report ${ago(updated)}`} tools={<Link to="/performance" className="btn xs ghost">Details <Icon name="arrow-right" className="xs" /></Link>} flush>
      <table className="dg">
        <thead><tr><th style={{ width: 40 }}>#</th><th>Model</th><th style={{ width: "28%" }}>Median abs. error</th><th className="r">Within ±20%</th><th className="r">Bias</th><th className="r">Rank corr.</th><th className="r">N</th></tr></thead>
        <tbody>
          {data.map((r, i) => {
            const m = String(r.Model);
            const e = r["MedAPE %"] as number;
            const isHM = m === "HYBRID MODEL";
            return (
              <tr key={m} style={isHM ? { background: "#ad80d70c" } : undefined}>
                <td className="mono faint">{i + 1}</td>
                <td className={isHM ? "hm" : "strong"} style={{ fontWeight: isHM ? 700 : 500 }}>{m}</td>
                <td><div className="row"><div className="lb-bar grow"><span style={{ width: `${(e / maxE) * 100}%`, background: isHM ? HM_COLOR : i === 0 ? "var(--up)" : "#57A3F8" }} /></div><span className="mono" style={{ width: 52, textAlign: "right" }}>{pctUnits(e, 1)}</span></div></td>
                <td className="r mono">{pctUnits(r["Hit +/-20%"], 1)}</td>
                <td className={`r mono ${isNum(r["Bias %"]) ? ((r["Bias %"] as number) >= 0 ? "up" : "down") : ""}`}>{pctUnits(r["Bias %"], 1)}</td>
                <td className="r mono">{isNum(r.Spearman) ? (r.Spearman as number).toFixed(2) : "—"}</td>
                <td className="r mono faint">{isNum(r.N) ? (r.N as number).toFixed(0) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
