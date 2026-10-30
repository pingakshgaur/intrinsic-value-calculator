import { ReactNode, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { isOpen, useChart, useWatchMutations, WatchItem } from "../lib/live";
import { isNum, money, num, pct, shortName, when } from "../lib/format";
import { ErrorNote, Icon, LabelBadge, Skeleton } from "./ui";
import { Level, TradingChart } from "./TradingChart";
import { SimpleChart } from "./SimpleChart";
import { useApp } from "./workbenchContext";
import { companyPath } from "../lib/company";

const RANGES = [["1d", "1D"], ["5d", "5D"], ["1mo", "1M"], ["6mo", "6M"], ["1y", "1Y"], ["5y", "5Y"], ["max", "Max"]] as const;
const SIMPLE_RANGES = ["1d", "5d", "1mo", "6mo", "1y"];

export function ChartPanel({ ticker, watch, height = 400, extra, compactHead, hideName, simple }: {
  ticker: string;
  watch?: WatchItem | null;
  height?: number;
  extra?: ReactNode;
  compactHead?: boolean;
  /** the company is already named just above (a side panel): show the price alone */
  hideName?: boolean;
  /** a quiet line chart with a few ranges, for narrow side panels */
  simple?: boolean;
}) {
  const [range, setRange] = useState<string>(() => { try { return localStorage.getItem("chart.range") || "1d"; } catch { return "1d"; } });
  const pick = (r: string) => { setRange(r); try { localStorage.setItem("chart.range", r); } catch { /* ignore */ } };
  const shown = simple && !SIMPLE_RANGES.includes(range) ? "1d" : range;
  const q = useChart(ticker, shown);
  const m = useWatchMutations();
  const app = useApp();
  const d = q.data && q.data.ticker === ticker ? q.data : null;
  const hm = d?.hm;
  const isIndex = ticker.startsWith("^") || ticker.startsWith("NIFTY_");

  const levels = useMemo(() => {
    const l: Level[] = [];
    if (hm?.value) l.push({ price: hm.value, color: "var(--hm)", title: "HYBRID MODEL" });
    if (hm?.buy_below) l.push({ price: hm.buy_below, color: "var(--up)", title: "Buy-below" });
    if (shown === "1d" && d?.prev_close) l.push({ price: d.prev_close, color: "var(--fg-3)", title: "Prev close" });
    if (watch?.alert_below) l.push({ price: watch.alert_below, color: "var(--c-yellow)", title: "Alert ↓" });
    if (watch?.alert_above) l.push({ price: watch.alert_above, color: "var(--c-yellow)", title: "Alert ↑" });
    return l;
  }, [hm?.value, hm?.buy_below, shown, d?.prev_close, watch?.alert_below, watch?.alert_above]);

  const bars = d?.bars ?? [];
  const day = shown === "1d" && bars.length ? {
    open: bars[0].o, high: Math.max(...bars.map((b) => b.h ?? -Infinity)), low: Math.min(...bars.map((b) => b.l ?? Infinity)),
    vol: bars.reduce((a, b) => a + (b.v || 0), 0),
  } : null;
  const tracked = d?.tracked ?? !!watch;
  const toggleTrack = () => {
    if (tracked) m.remove.mutate(ticker, { onSuccess: () => app.toast(`Stopped tracking ${ticker}`) });
    else m.add.mutate({ ticker, name: d?.meta.name, sector: d?.meta.sector, cap: d?.meta.cap }, {
      onSuccess: () => app.toast(`Tracking ${d?.meta.name ?? ticker} — it also joins the learning data`, "ok"),
      onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
    });
  };
  const ranges = simple ? RANGES.filter(([k]) => SIMPLE_RANGES.includes(k)) : watch ? [...RANGES, ["tracked", "Tracked"] as const] : RANGES;
  const setAlert = (kind: "below" | "above", price: number) => m.update.mutate({ ticker, [`alert_${kind}`]: price }, {
    onSuccess: () => app.toast(`Alert set: ${kind === "below" ? "at or below" : "at or above"} ${num(price)}`, "ok"),
    onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
  });

  return (
    <div className="cpanel">
      <div className="cp-head">
        <div className="grow" style={{ minWidth: 0 }} hidden={hideName}>
          <div className="row" style={{ gap: 8 }}>
            <b className="cp-name ellipsis">{d ? shortName(d.meta.name) : ticker}</b>
            <span className="mono faint xs">{ticker}</span>
            {d?.meta.lists.includes("coverage") && <span className="tag hm" title="On the report list (data/companies.csv)">report list</span>}
          </div>
          {!compactHead && d?.meta.sector && <div className="xs faint">{d.meta.sector}{d.meta.cap ? ` · ${d.meta.cap} cap` : ""}</div>}
        </div>
        <div className="cp-px">
          <span className="v">{d ? num(d.last, 2) : "—"}</span>
          {d && <span className={`d ${isNum(d.chg_pct) ? (d.chg_pct >= 0 ? "up" : "down") : ""}`}>{isNum(d.chg_pct) ? `${d.chg_pct >= 0 ? "▲" : "▼"} ${pct(Math.abs(d.chg_pct), 2)}` : ""}<small>{shown === "1d" ? "today" : RANGES.find((r) => r[0] === shown)?.[1] ?? shown}</small></span>}
        </div>
      </div>
      <div className="cp-tools">
        <div className="seg">{ranges.map(([k, l]) => <button key={k} className={shown === k ? "on" : ""} onClick={() => pick(k)}>{l}</button>)}</div>
        <span className="spacer" />
        {q.isFetching && <Icon name="loading" className="xs spin faint" />}
        {d && <span className={`live-dot ${isOpen(d.market) ? "on" : ""}`}>{isOpen(d.market) ? "Live" : "Market closed"}</span>}
        {!isIndex && <button className={`btn xs ${tracked ? "sec" : ""}`} onClick={toggleTrack} disabled={m.add.isPending || m.remove.isPending}>
          <Icon name={tracked ? "eye-closed" : "eye"} className="xs" />{tracked ? "Untrack" : "Track"}
        </button>}
      </div>
      <div className="cp-chart">
        {q.isError && !d ? <div style={{ padding: 16 }}><ErrorNote error={q.error} onRetry={() => q.refetch()} /></div>
          : !d ? <div style={{ padding: 16 }}><Skeleton h={height - 32} /></div>
          : shown === "tracked" && !bars.length ? <div className="empty" style={{ height }}><Icon name="history" /><span className="small">No stored minute bars yet — the tracker saves them on every poll.</span></div>
          : simple ? <SimpleChart bars={bars} levels={levels} height={height} intraday={["1d", "5d"].includes(shown)} base={shown === "1d" ? d.prev_close : null} />
          : <TradingChart bars={bars} levels={levels} height={height} resetKey={`${ticker}|${shown}`} ticker={ticker} title={d.meta.name !== ticker ? shortName(d.meta.name) : ticker}
              intraday={["1d", "5d", "1mo", "tracked"].includes(shown)} prevClose={shown === "1d" ? d.prev_close : null}
              onAlert={tracked && !isIndex ? setAlert : undefined} />}
      </div>
      <div className="cp-figs">
        {day ? <>
          <div><span>Open</span><b>{num(day.open)}</b></div>
          <div><span>High</span><b>{num(day.high)}</b></div>
          <div><span>Low</span><b>{num(day.low)}</b></div>
          <div><span>Prev close</span><b>{num(d?.prev_close)}</b></div>
          <div><span>Volume</span><b>{isNum(day.vol) ? day.vol.toLocaleString("en-IN") : "—"}</b></div>
        </> : bars.length > 1 ? <>
          <div><span>Period high</span><b>{num(Math.max(...bars.map((b) => b.h ?? -Infinity)))}</b></div>
          <div><span>Period low</span><b>{num(Math.min(...bars.map((b) => b.l ?? Infinity)))}</b></div>
          <div><span>Bars</span><b>{bars.length.toLocaleString("en-IN")}{d?.stored ? ` · ${d.stored.toLocaleString("en-IN")} stored` : ""}</b></div>
          <div><span>From</span><b>{when(bars[0].t).split(",")[0]}</b></div>
        </> : null}
      </div>
      {hm && (
        <div className="cp-hm">
          <div className="row" style={{ gap: 8 }}>
            <span className="tag hm">HYBRID MODEL at the live price</span>
            <LabelBadge label={hm.label} />
            <span className="spacer" />
            <Link className="xs" to={companyPath(hm.company)}>Full analysis</Link>
          </div>
          <div className="cp-figs" style={{ border: 0, padding: 0 }}>
            <div><span>Value</span><b style={{ color: "var(--hm)" }}>{money(hm.value, 0)}</b></div>
            <div><span>Upside</span><b className={isNum(hm.upside) ? (hm.upside >= 0 ? "up" : "down") : ""}>{pct(hm.upside, 1, true)}</b></div>
            <div><span>Buy-below</span><b>{money(hm.buy_below, 0)}</b></div>
            <div><span>Range P10–P90</span><b>{money(hm.low, 0)}–{money(hm.high, 0)}</b></div>
            <div><span>Confidence</span><b>{isNum(hm.confidence) ? hm.confidence.toFixed(0) : "—"}</b></div>
          </div>
          <div className="xs faint">Value from FY{hm.fy} accounts ({hm.source === "research" ? "latest research run" : "valuation report"}); only the price is live.</div>
        </div>
      )}
      {extra}
      {simple && <Link className="xs cp-full" to={`/markets?t=${encodeURIComponent(ticker)}`}><Icon name="graph-line" className="xs" />Full chart with indicators and drawing tools</Link>}
      {d?.note && <div className="xs warn cp-foot"><Icon name="info" className="xs" /> {d.note}</div>}
      {d && <div className="xs faint cp-foot">{d.market.delay_note}. {d.market.ist}.</div>}
    </div>
  );
}
