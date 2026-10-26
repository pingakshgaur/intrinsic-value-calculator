import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType, createChart, CrosshairMode, IChartApi, IPriceLine, ISeriesApi, LineStyle, Logical, LogicalRange, MouseEventParams,
  PriceScaleMode, SeriesType, UTCTimestamp,
} from "lightweight-charts";
import { Bar } from "../lib/live";
import { bollinger, ema, heikinAshi, macd, rsi, sma, vwap } from "../lib/indicators";
import { ThemeColors, themeColors, useTheme } from "../lib/theme";
import { isNum } from "../lib/format";
import { Icon } from "./ui";
import { ExportButton } from "./ExportButton";

// Lightweight Charts draws timestamps as UTC; shifting by +5:30 shows the
// axis in Indian market time whatever the viewer's own time zone is.
const IST = 19800;

export interface Level { price: number; color: string; title: string; dashed?: boolean }

type ChartType = "candle" | "hollow" | "heikin" | "bar" | "line" | "area" | "baseline";
type IndKey = "volume" | "sma20" | "sma50" | "sma200" | "ema9" | "ema21" | "bb" | "vwap" | "rsi" | "macd";
type Scale = "auto" | "log" | "pct";
type Tool = "cursor" | "trend" | "ray" | "hline" | "vline" | "rect" | "fib" | "measure" | "note" | "eraser";
interface Pt { t: number; p: number }
interface Drawing { id: string; kind: Exclude<Tool, "cursor" | "measure" | "eraser">; a: Pt; b?: Pt; text?: string }
interface Prefs { type: ChartType; ind: Record<IndKey, boolean>; scale: Scale; tooltip: boolean; magnet: boolean }

const TYPES: { id: ChartType; label: string }[] = [
  { id: "candle", label: "Candles" }, { id: "hollow", label: "Hollow candles" }, { id: "heikin", label: "Heikin-Ashi" },
  { id: "bar", label: "Bars (OHLC)" }, { id: "line", label: "Line" }, { id: "area", label: "Area" }, { id: "baseline", label: "Baseline" },
];
const INDS: { id: IndKey; label: string; pane?: boolean; formula: string }[] = [
  { id: "volume", label: "Volume", formula: "shares traded per bar, green when the bar closed up" },
  { id: "sma20", label: "SMA 20", formula: "SMA = (C₁ + … + C₂₀) ÷ 20" },
  { id: "sma50", label: "SMA 50", formula: "SMA = (C₁ + … + C₅₀) ÷ 50" },
  { id: "sma200", label: "SMA 200", formula: "SMA = (C₁ + … + C₂₀₀) ÷ 200" },
  { id: "ema9", label: "EMA 9", formula: "EMAₜ = α·Cₜ + (1 − α)·EMAₜ₋₁, α = 2 ÷ (9 + 1)" },
  { id: "ema21", label: "EMA 21", formula: "EMAₜ = α·Cₜ + (1 − α)·EMAₜ₋₁, α = 2 ÷ (21 + 1)" },
  { id: "bb", label: "Bollinger Bands 20, 2", formula: "SMA20 ± 2 × standard deviation of 20 closes" },
  { id: "vwap", label: "VWAP", formula: "Σ(typical price × volume) ÷ Σ volume, restarting each day · intraday" },
  { id: "rsi", label: "RSI 14", pane: true, formula: "100 − 100 ÷ (1 + average gain ÷ average loss), Wilder 14" },
  { id: "macd", label: "MACD 12 26 9", pane: true, formula: "EMA12 − EMA26; signal = EMA9 of MACD; histogram = MACD − signal" },
];
const TOOLS: { id: Tool; label: string; key?: string }[] = [
  { id: "cursor", label: "Crosshair", key: "Esc" }, { id: "trend", label: "Trend line" }, { id: "ray", label: "Ray" },
  { id: "hline", label: "Horizontal line" }, { id: "vline", label: "Vertical line" }, { id: "rect", label: "Rectangle" },
  { id: "fib", label: "Fibonacci retracement" }, { id: "measure", label: "Measure" }, { id: "note", label: "Note" },
  { id: "eraser", label: "Eraser — click a drawing" },
];
const FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
const DEFAULT_PREFS: Prefs = {
  type: "candle", scale: "auto", tooltip: true, magnet: false,
  ind: { volume: true, sma20: false, sma50: false, sma200: false, ema9: false, ema21: false, bb: false, vwap: false, rsi: false, macd: false },
};

function usePrefs(): [Prefs, (p: Partial<Prefs>) => void] {
  const [p, setP] = useState<Prefs>(() => {
    try { const s = JSON.parse(localStorage.getItem("chart.prefs.v2") || "{}"); return { ...DEFAULT_PREFS, ...s, ind: { ...DEFAULT_PREFS.ind, ...(s.ind || {}) } }; } catch { return DEFAULT_PREFS; }
  });
  const set = useCallback((patch: Partial<Prefs>) => setP((cur) => {
    const n = { ...cur, ...patch };
    try { localStorage.setItem("chart.prefs.v2", JSON.stringify(n)); } catch { /* private mode */ }
    return n;
  }), []);
  return [p, set];
}

function useDrawings(ticker: string): [Drawing[], (f: (d: Drawing[]) => Drawing[]) => void] {
  const key = `chart.draw.v1.${ticker}`;
  const [d, setD] = useState<Drawing[]>([]);
  useEffect(() => { try { setD(JSON.parse(localStorage.getItem(key) || "[]")); } catch { setD([]); } }, [key]);
  const update = useCallback((f: (d: Drawing[]) => Drawing[]) => setD((cur) => {
    const n = f(cur);
    try { localStorage.setItem(key, JSON.stringify(n)); } catch { /* private mode */ }
    return n;
  }), [key]);
  return [d, update];
}

const alpha = (hex: string, a: number) => {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6);
  return `#${full}${Math.round(a * 255).toString(16).padStart(2, "0")}`;
};
const resolve = (c: string) => {
  const m = /^var\((--[\w-]+)\)$/.exec(c.trim());
  return m ? getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() || c : c;
};
const fmtP = (p: number | null | undefined, d = 2) => (isNum(p) ? p.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }) : "—");
const fmtV = (v: number) => (v >= 1e7 ? (v / 1e7).toFixed(2) + " Cr" : v >= 1e5 ? (v / 1e5).toFixed(2) + " L" : v >= 1e3 ? (v / 1e3).toFixed(1) + " K" : String(v));
function fmtT(t: number, intraday: boolean) {
  const d = new Date((t + IST) * 1000);
  const day = `${d.getUTCDate()} ${d.toLocaleString("en-GB", { month: "short", timeZone: "UTC" })} ${d.getUTCFullYear()}`;
  return intraday ? `${day}, ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}` : day;
}
const uid = () => Math.random().toString(36).slice(2, 10);

function indColors(c: ThemeColors): Record<string, string> {
  const light = c.theme === "light";
  return { sma20: c.blue, sma50: c.orange, sma200: c.purple, ema9: light ? "#0f8a7a" : "#4ec9b0", ema21: c.yellow,
    bb: c.fg3, vwap: light ? "#a03ca0" : "#c586c0", rsi: c.purple, macd: c.blue, signal: c.orange };
}

export function TradingChart({ bars, levels = [], resetKey, intraday, ticker, height = 420, prevClose, onAlert, title }: {
  bars: Bar[];
  levels?: Level[];
  /** zoom resets to fit only when this changes (new ticker / range), not on every live refresh */
  resetKey: string;
  intraday?: boolean;
  ticker: string;
  height?: number | string;
  prevClose?: number | null;
  /** present when the company is tracked: right-click can set its alerts */
  onAlert?: (kind: "below" | "above", price: number) => void;
  title?: string;
}) {
  const theme = useTheme();
  const cols = useMemo(() => themeColors(), [theme]); // eslint-disable-line react-hooks/exhaustive-deps
  const [prefs, setPrefs] = usePrefs();
  const [tool, setTool] = useState<Tool>("cursor");
  const [drawings, setDrawings] = useDrawings(ticker);
  const [draft, setDraft] = useState<{ kind: Tool; a: Pt; b: Pt; waiting?: boolean } | null>(null);
  const [measure, setMeasure] = useState<{ a: Pt; b: Pt } | null>(null);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; pt: Pt; hit: string | null } | null>(null);
  const [note, setNote] = useState<{ pt: Pt; x: number; y: number; text: string } | null>(null);
  const [open, setOpen] = useState<"type" | "ind" | null>(null);
  const [, setTick] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const main = useRef<ISeriesApi<SeriesType> | null>(null);
  const extra = useRef<ISeriesApi<SeriesType>[]>([]);
  const lines = useRef<IPriceLine[]>([]);
  const built = useRef("");
  const fitted = useRef("");
  const raf = useRef(0);
  const paneBoxes = useRef<Record<string, HTMLDivElement | null>>({});
  const paneCharts = useRef<Record<string, { chart: IChartApi; series: ISeriesApi<SeriesType>[] }>>({});
  const xsync = useRef(false);
  const syncRef = useRef<(time: MouseEventParams["time"] | null, i: number, skip?: IChartApi) => void>(() => undefined);

  const data = useMemo(() => bars.filter((b) => isNum(b.o) && isNum(b.h) && isNum(b.l) && isNum(b.c)), [bars]);
  const dataRef = useRef(data);
  dataRef.current = data;
  const closes = useMemo(() => data.map((b) => b.c!), [data]);
  const calc = useMemo(() => ({
    sma20: prefs.ind.sma20 ? sma(closes, 20) : null, sma50: prefs.ind.sma50 ? sma(closes, 50) : null,
    sma200: prefs.ind.sma200 ? sma(closes, 200) : null, ema9: prefs.ind.ema9 ? ema(closes, 9) : null,
    ema21: prefs.ind.ema21 ? ema(closes, 21) : null, bb: prefs.ind.bb ? bollinger(closes, 20, 2) : null,
    vwap: prefs.ind.vwap && intraday ? vwap(data) : null, rsi: prefs.ind.rsi ? rsi(closes, 14) : null,
    macd: prefs.ind.macd ? macd(closes) : null,
  }), [closes, data, prefs.ind, intraday]);
  const panes = (["rsi", "macd"] as const).filter((k) => prefs.ind[k]);

  const bump = useCallback(() => {
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(() => setTick((t) => t + 1));
  }, []);

  // ---------------------------------------------------------------- chart
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, fontSize: 11, fontFamily: "Inter Variable, Inter, Segoe UI, sans-serif" },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 6 },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { priceFormatter: (p: number) => fmtP(p) },
    });
    chart.current = c;
    c.timeScale().subscribeVisibleLogicalRangeChange(bump);
    c.subscribeCrosshairMove((p: MouseEventParams) => {
      if (xsync.current) return;
      xsync.current = true;
      try {
        if (!p.point || p.logical == null) { setHover(null); syncRef.current(null, -1); return; }
        const i = Math.round(p.logical as number);
        setHover(i >= 0 && i < dataRef.current.length ? { i, x: p.point.x, y: p.point.y } : null);
        syncRef.current(p.time ?? null, i);
        bump();
      } finally { xsync.current = false; }
    });
    const ro = new ResizeObserver(bump);
    ro.observe(box.current);
    const fs = () => bump();
    document.addEventListener("fullscreenchange", fs);
    return () => {
      ro.disconnect();
      document.removeEventListener("fullscreenchange", fs);
      cancelAnimationFrame(raf.current);
      c.remove();
      chart.current = null; main.current = null; extra.current = []; lines.current = []; built.current = ""; fitted.current = "";
    };
  }, [bump]);

  useEffect(() => {
    chart.current?.applyOptions({
      layout: { textColor: cols.fg2 },
      grid: { vertLines: { color: cols.grid }, horzLines: { color: cols.grid } },
      rightPriceScale: { borderColor: cols.line, minimumWidth: 74 },
      timeScale: { borderColor: cols.line, timeVisible: !!intraday, visible: panes.length === 0 },
      crosshair: { mode: prefs.magnet ? CrosshairMode.Magnet : CrosshairMode.Normal,
        vertLine: { color: alpha(cols.fg3, 0.8), labelBackgroundColor: cols.fg2 }, horzLine: { color: alpha(cols.fg3, 0.8), labelBackgroundColor: cols.fg2 } },
      handleScroll: tool === "cursor", handleScale: tool === "cursor",
    });
  }, [cols, intraday, prefs.magnet, tool, panes.length]);

  // series: rebuilt when their kind changes, data refreshed in place otherwise
  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    const key = JSON.stringify([prefs.type, prefs.ind, cols.theme, !!intraday, prevClose ?? null]);
    if (key !== built.current) {
      if (main.current) c.removeSeries(main.current);
      for (const s of extra.current) c.removeSeries(s);
      extra.current = []; lines.current = [];
      const t = prefs.type;
      main.current = t === "candle" || t === "heikin"
        ? c.addCandlestickSeries({ upColor: cols.up, downColor: cols.down, wickUpColor: cols.up, wickDownColor: cols.down, borderVisible: false })
        : t === "hollow"
          ? c.addCandlestickSeries({ upColor: "rgba(0,0,0,0)", downColor: cols.down, borderUpColor: cols.up, borderDownColor: cols.down, wickUpColor: cols.up, wickDownColor: cols.down, borderVisible: true })
          : t === "bar" ? c.addBarSeries({ upColor: cols.up, downColor: cols.down, thinBars: false })
            : t === "line" ? c.addLineSeries({ color: cols.blue, lineWidth: 2 })
              : t === "area" ? c.addAreaSeries({ lineColor: cols.blue, topColor: alpha(cols.blue, 0.28), bottomColor: alpha(cols.blue, 0.02), lineWidth: 2 })
                : c.addBaselineSeries({ baseValue: { type: "price", price: prevClose ?? data[0]?.c ?? 0 }, topLineColor: cols.up, topFillColor1: alpha(cols.up, 0.25), topFillColor2: alpha(cols.up, 0.03), bottomLineColor: cols.down, bottomFillColor1: alpha(cols.down, 0.03), bottomFillColor2: alpha(cols.down, 0.25), lineWidth: 2 });
      const ic = indColors(cols);
      const line = (color: string, scale?: string, width: 1 | 2 = 1) => {
        const s = c.addLineSeries({ color, lineWidth: width, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceScaleId: scale });
        extra.current.push(s);
        return s;
      };
      if (prefs.ind.volume) extra.current.push(c.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false }));
      for (const k of ["sma20", "sma50", "sma200", "ema9", "ema21"] as const) if (prefs.ind[k]) line(ic[k]);
      if (prefs.ind.bb) { line(ic.bb); line(alpha(ic.bb, 0.6)); line(alpha(ic.bb, 0.6)); }
      if (prefs.ind.vwap && intraday) line(ic.vwap, undefined, 2);
      built.current = key;
    }
    // data
    const time = (b: Bar) => (b.t + IST) as UTCTimestamp;
    const s = main.current!;
    const src = prefs.type === "heikin" ? heikinAshi(data) : data;
    if (["candle", "hollow", "heikin", "bar"].includes(prefs.type)) {
      (s as ISeriesApi<"Candlestick">).setData(src.map((b) => ({ time: time(b), open: b.o!, high: b.h!, low: b.l!, close: b.c! })));
    } else {
      (s as ISeriesApi<"Line">).setData(data.map((b) => ({ time: time(b), value: b.c! })));
    }
    let n = 0;
    const next = () => extra.current[n++];
    const put = (vals: (number | null)[] | null | undefined) => {
      const ser = next();
      ser?.setData(data.map((b, i) => (isNum(vals?.[i]) ? { time: time(b), value: vals![i]! } : { time: time(b) })));
    };
    if (prefs.ind.volume) (next() as ISeriesApi<"Histogram">).setData(data.map((b) => ({ time: time(b), value: b.v, color: alpha(b.c! >= b.o! ? cols.up : cols.down, 0.4) })));
    for (const k of ["sma20", "sma50", "sma200", "ema9", "ema21"] as const) if (prefs.ind[k]) put(calc[k]);
    if (calc.bb) { put(calc.bb.mid); put(calc.bb.up); put(calc.bb.lo); }
    if (prefs.ind.vwap && intraday) put(calc.vwap);
    s.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: prefs.ind.volume ? 0.17 : 0.05 },
      mode: prefs.scale === "log" ? PriceScaleMode.Logarithmic : prefs.scale === "pct" ? PriceScaleMode.Percentage : PriceScaleMode.Normal });
    if (prefs.ind.volume) c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    const fk = `${resetKey}|${prefs.type}`;
    if (fitted.current !== fk && data.length) { c.timeScale().fitContent(); fitted.current = fk; }
    bump();
  }, [data, calc, prefs.type, prefs.ind, prefs.scale, cols, intraday, prevClose, resetKey, bump]); // eslint-disable-line react-hooks/exhaustive-deps

  // RSI and MACD: their own charts under the price chart, each with its own
  // scale, kept in step with it (zoom, scroll and crosshair)
  const panesKey = panes.join(",");
  useEffect(() => {
    const m = chart.current;
    if (!m || !panes.length) return;
    const made: Record<string, { chart: IChartApi; series: ISeriesApi<SeriesType>[] }> = {};
    const ic = indColors(cols);
    panes.forEach((id, i) => {
      const el = paneBoxes.current[id];
      if (!el) return;
      const pc = createChart(el, {
        autoSize: true,
        // the TradingView attribution stays on the price chart above
        layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cols.fg2, fontSize: 11, fontFamily: "Inter Variable, Inter, Segoe UI, sans-serif", attributionLogo: false },
        grid: { vertLines: { color: cols.grid }, horzLines: { color: cols.grid } },
        rightPriceScale: { borderColor: cols.line, minimumWidth: 74, scaleMargins: { top: 0.14, bottom: 0.06 } },
        timeScale: { borderColor: cols.line, visible: i === panes.length - 1, timeVisible: !!intraday, secondsVisible: false, rightOffset: 6 },
        crosshair: { mode: CrosshairMode.Normal, vertLine: { color: alpha(cols.fg3, 0.8), labelBackgroundColor: cols.fg2 }, horzLine: { color: alpha(cols.fg3, 0.8), labelBackgroundColor: cols.fg2 } },
        localization: { priceFormatter: (p: number) => fmtP(p) },
      });
      const opts = { priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false };
      const series: ISeriesApi<SeriesType>[] = [];
      if (id === "rsi") {
        const r = pc.addLineSeries({ ...opts, color: ic.rsi, lineWidth: 1 });
        r.createPriceLine({ price: 70, color: alpha(cols.down, 0.7), lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "" });
        r.createPriceLine({ price: 30, color: alpha(cols.up, 0.7), lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "" });
        series.push(r);
      } else {
        series.push(pc.addHistogramSeries({ ...opts, lastValueVisible: false }));
        series.push(pc.addLineSeries({ ...opts, color: ic.macd, lineWidth: 1 }));
        series.push(pc.addLineSeries({ ...opts, color: ic.signal, lineWidth: 1 }));
      }
      made[id] = { chart: pc, series };
    });
    paneCharts.current = made;
    const all = [m, ...Object.values(made).map((x) => x.chart)];
    let busy = false;
    const subs = all.map((src) => {
      const h = (r: LogicalRange | null) => {
        if (busy || !r) return;
        busy = true;
        for (const o of all) if (o !== src) o.timeScale().setVisibleLogicalRange(r);
        busy = false;
      };
      src.timeScale().subscribeVisibleLogicalRangeChange(h);
      return [src, h] as const;
    });
    const moves = Object.values(made).map((x) => {
      const h = (p: MouseEventParams) => {
        if (xsync.current) return;
        xsync.current = true;
        try {
          if (p.time != null && p.logical != null) {
            const i = Math.round(p.logical as number);
            const b = dataRef.current[i];
            if (b && main.current) m.setCrosshairPosition(b.c!, p.time, main.current);
            syncRef.current(p.time, i, x.chart);
            setHover(b ? { i, x: -1, y: -1 } : null);
          } else {
            m.clearCrosshairPosition();
            syncRef.current(null, -1, x.chart);
            setHover(null);
          }
        } finally { xsync.current = false; }
      };
      x.chart.subscribeCrosshairMove(h);
      return [x.chart, h] as const;
    });
    const r = m.timeScale().getVisibleLogicalRange();
    if (r) for (const x of Object.values(made)) x.chart.timeScale().setVisibleLogicalRange(r);
    bump();
    return () => {
      for (const [src, h] of subs) src.timeScale().unsubscribeVisibleLogicalRangeChange(h);
      for (const [c, h] of moves) c.unsubscribeCrosshairMove(h);
      for (const x of Object.values(made)) x.chart.remove();
      paneCharts.current = {};
    };
  }, [panesKey, cols, intraday]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const time = (b: Bar) => (b.t + IST) as UTCTimestamp;
    const put = (s: ISeriesApi<SeriesType> | undefined, vals: (number | null)[]) =>
      s?.setData(data.map((b, i) => (isNum(vals[i]) ? { time: time(b), value: vals[i]! } : { time: time(b) })));
    const pr = paneCharts.current.rsi, pm = paneCharts.current.macd;
    if (pr && calc.rsi) put(pr.series[0], calc.rsi);
    if (pm && calc.macd) {
      (pm.series[0] as ISeriesApi<"Histogram">).setData(data.map((b, i) => {
        const h = calc.macd!.hist[i];
        return isNum(h) ? { time: time(b), value: h, color: alpha(h >= 0 ? cols.up : cols.down, 0.55) } : { time: time(b) };
      }));
      put(pm.series[1], calc.macd.line);
      put(pm.series[2], calc.macd.signal);
    }
    const r = chart.current?.timeScale().getVisibleLogicalRange();
    if (r) for (const x of Object.values(paneCharts.current)) x.chart.timeScale().setVisibleLogicalRange(r);
  }, [data, calc, panesKey, cols]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Mirror a crosshair position (bar index i) onto every pane except `skip`. */
  syncRef.current = (time, i, skip) => {
    for (const [id, x] of Object.entries(paneCharts.current)) {
      if (x.chart === skip) continue;
      const v = (id === "rsi" ? calc.rsi : calc.macd?.line)?.[i];
      if (time != null && isNum(v)) x.chart.setCrosshairPosition(v, time, x.series[id === "rsi" ? 0 : 1]);
      else x.chart.clearCrosshairPosition();
    }
  };

  useEffect(() => {
    const s = main.current;
    if (!s) return;
    for (const l of lines.current) { try { s.removePriceLine(l); } catch { /* series rebuilt */ } }
    lines.current = levels.filter((l) => isNum(l.price) && l.price > 0).map((l) => s.createPriceLine({
      price: l.price, color: resolve(l.color), lineWidth: 1, lineStyle: l.dashed === false ? LineStyle.Solid : LineStyle.Dashed,
      axisLabelVisible: true, title: l.title,
    }));
  }, [levels, prefs.type, prefs.ind, cols, data]);

  // ---------------------------------------------------------------- coordinates
  const times = useMemo(() => data.map((b) => b.t), [data]);
  const tToL = (t: number) => {
    const n = times.length;
    if (!n) return 0;
    const step = (i: number) => (n > 1 ? times[Math.min(n - 1, i + 1)] - times[Math.min(n - 2, i)] : 60) || 60;
    if (t <= times[0]) return (t - times[0]) / step(0);
    if (t >= times[n - 1]) return n - 1 + (t - times[n - 1]) / step(n - 2);
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (times[m] <= t) lo = m; else hi = m; }
    return lo + (t - times[lo]) / (times[hi] - times[lo] || 1);
  };
  const lToT = (l: number) => {
    const n = times.length;
    if (!n) return 0;
    const step = n > 1 ? (times[n - 1] - times[0]) / (n - 1) : 60;
    if (l <= 0) return times[0] + l * (n > 1 ? times[1] - times[0] : step);
    if (l >= n - 1) return times[n - 1] + (l - (n - 1)) * (n > 1 ? times[n - 1] - times[n - 2] : step);
    const i = Math.floor(l);
    return times[i] + (l - i) * (times[i + 1] - times[i]);
  };
  const xy = (p: Pt) => {
    const x = chart.current?.timeScale().logicalToCoordinate(tToL(p.t) as Logical);
    const y = main.current?.priceToCoordinate(p.p);
    return x == null || y == null ? null : { x, y };
  };
  const pt = (x: number, y: number): Pt | null => {
    const l = chart.current?.timeScale().coordinateToLogical(x);
    const p = main.current?.coordinateToPrice(y);
    if (l == null || p == null) return null;
    if (prefs.magnet) {
      const b = data[Math.max(0, Math.min(data.length - 1, Math.round(l as number)))];
      if (b) {
        const snap = [b.o!, b.h!, b.l!, b.c!].reduce((a, v) => (Math.abs(v - p) < Math.abs(a - p) ? v : a));
        return { t: b.t, p: snap };
      }
    }
    return { t: lToT(l as number), p };
  };
  const local = (e: { clientX: number; clientY: number }) => {
    const r = box.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  // ---------------------------------------------------------------- drawing
  const add = (d: Omit<Drawing, "id">) => setDrawings((cur) => [...cur, { ...d, id: uid() }]);
  const finish = (kind: Tool, a: Pt, b: Pt) => {
    if (kind === "measure") setMeasure({ a, b });
    else add({ kind: kind as Drawing["kind"], a, b });
    setDraft(null);
    setTool("cursor");
  };
  const distSeg = (px: number, py: number, ax: number, ay: number, bx: number, by: number, ray = false) => {
    const dx = bx - ax, dy = by - ay;
    let t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy || 1);
    t = ray ? Math.max(0, t) : Math.max(0, Math.min(1, t));
    return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
  };
  const hit = (x: number, y: number): string | null => {
    let best: [number, string] | null = null;
    for (const d of drawings) {
      const A = xy(d.a), B = d.b ? xy(d.b) : null;
      let dist = Infinity;
      if (d.kind === "hline" && A) dist = Math.abs(y - A.y);
      else if (d.kind === "vline" && A) dist = Math.abs(x - A.x);
      else if (d.kind === "note" && A) dist = x >= A.x - 4 && x <= A.x + 8 + (d.text?.length ?? 0) * 7 && y >= A.y - 22 && y <= A.y + 4 ? 0 : Infinity;
      else if (A && B && (d.kind === "trend" || d.kind === "ray")) dist = distSeg(x, y, A.x, A.y, B.x, B.y, d.kind === "ray");
      else if (A && B && d.kind === "rect") {
        const inside = x >= Math.min(A.x, B.x) && x <= Math.max(A.x, B.x) && y >= Math.min(A.y, B.y) && y <= Math.max(A.y, B.y);
        dist = inside ? 0 : Infinity;
      } else if (A && B && d.kind === "fib" && x >= Math.min(A.x, B.x) - 4 && x <= Math.max(A.x, B.x) + 4) {
        dist = Math.min(...FIB.map((f) => Math.abs(y - (A.y + (B.y - A.y) * f))));
      }
      if (dist < 7 && (!best || dist < best[0])) best = [dist, d.id];
    }
    return best ? best[1] : null;
  };

  const onDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    setMenu(null); setOpen(null);
    if (tool === "cursor") { if (measure) setMeasure(null); return; }
    const { x, y } = local(e);
    const p = pt(x, y);
    if (!p) return;
    e.preventDefault();
    if (tool === "hline" || tool === "vline") { add({ kind: tool, a: p }); setTool("cursor"); return; }
    if (tool === "note") { setNote({ pt: p, x, y, text: "" }); setTool("cursor"); return; }
    if (tool === "eraser") { const id = hit(x, y); if (id) setDrawings((cur) => cur.filter((d) => d.id !== id)); return; }
    if (draft?.waiting) { finish(draft.kind, draft.a, p); return; }
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setDraft({ kind: tool, a: p, b: p });
  };
  const onMove = (e: React.PointerEvent) => {
    if (!draft) return;
    const { x, y } = local(e);
    const p = pt(x, y);
    if (p) setDraft({ ...draft, b: p });
  };
  const onUp = () => {
    if (!draft || draft.waiting) return;
    const A = xy(draft.a), B = xy(draft.b);
    if (A && B && Math.hypot(A.x - B.x, A.y - B.y) < 5) setDraft({ ...draft, waiting: true }); // click, then click again
    else finish(draft.kind, draft.a, draft.b);
  };
  const onContext = (e: React.MouseEvent) => {
    e.preventDefault();
    const { x, y } = local(e);
    const p = pt(x, y);
    if (p) setMenu({ x, y, pt: p, hit: hit(x, y) });
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { setTool("cursor"); setDraft(null); setMeasure(null); setMenu(null); setOpen(null); setNote(null); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); setDrawings((cur) => cur.slice(0, -1)); }
  };
  useEffect(() => {
    if (!menu && !open) return;
    const close = (ev: PointerEvent) => { if (!(ev.target as HTMLElement).closest?.(".tc-menu, .tc-drop")) { setMenu(null); setOpen(null); } };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [menu, open]);

  // ---------------------------------------------------------------- actions
  const reset = () => { chart.current?.timeScale().fitContent(); main.current?.priceScale().applyOptions({ autoScale: true }); setPrefs({ scale: "auto" }); };
  const fullscreen = () => {
    const el = (root.current?.closest(".cpanel") as HTMLElement | null) ?? root.current;
    if (document.fullscreenElement) document.exitFullscreen();
    else el?.requestFullscreen?.();
  };
  /** The chart, its drawings and its panes as one canvas. */
  const compose = async (): Promise<HTMLCanvasElement | null> => {
    const c = chart.current;
    if (!c) return null;
    const shot = c.takeScreenshot();
    const subs = Object.values(paneCharts.current).map((x) => x.chart.takeScreenshot());
    const head = Math.round(32 * (shot.width / (box.current?.clientWidth || shot.width)));
    const out = document.createElement("canvas");
    out.width = shot.width; out.height = shot.height + head + subs.reduce((a, s) => a + s.height, 0);
    const ctx = out.getContext("2d")!;
    ctx.fillStyle = cols.panel; ctx.fillRect(0, 0, out.width, out.height);
    ctx.fillStyle = cols.fg1; ctx.font = `600 ${Math.round(head * 0.45)}px Inter, sans-serif`;
    ctx.fillText(`${title ?? ticker} · ${resetKey.split("|")[1] ?? ""} · ${fmtT(data[data.length - 1]?.t ?? 0, !!intraday)} IST`, head * 0.4, head * 0.65);
    ctx.drawImage(shot, 0, head);
    if (svg.current) {
      const img = new Image();
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(svg.current));
      try { await img.decode(); ctx.drawImage(img, 0, head, shot.width, shot.height); } catch { /* drawings skipped */ }
    }
    let y = head + shot.height;
    for (const s of subs) { ctx.drawImage(s, 0, y); y += s.height; }
    return out;
  };
  const snapshot = async () => {
    const out = await compose();
    if (!out) return;
    const a = document.createElement("a");
    a.href = out.toDataURL("image/png");
    a.download = `${ticker.replace(/[^\w.-]/g, "_")}-${new Date().toISOString().slice(0, 10)}.png`;
    a.click();
  };

  // ---------------------------------------------------------------- overlay
  const W = box.current?.clientWidth ?? 0;
  const H = box.current?.clientHeight ?? 0;
  // the price axis, not the time axis: the latter is hidden (width 0) while panes sit below
  const plotW = Math.max(0, W - (chart.current?.priceScale("right").width() ?? 0));
  const plotH = Math.max(0, H - (chart.current?.timeScale().height() ?? 26));
  const draw = (d: { kind: string; a: Pt; b?: Pt; text?: string; id?: string }, preview = false) => {
    const A = xy(d.a), B = d.b ? xy(d.b) : null;
    const col = d.kind === "note" ? cols.yellow : cols.blue;
    const sw = preview ? 1.2 : 1.6;
    const key = d.id ?? "draft";
    if (d.kind === "hline" && A) return <g key={key}><line x1={0} x2={plotW} y1={A.y} y2={A.y} stroke={col} strokeWidth={sw} /><text x={plotW - 4} y={A.y - 4} textAnchor="end" fill={col} fontSize={10.5}>{fmtP(d.a.p)}</text></g>;
    if (d.kind === "vline" && A) return <g key={key}><line x1={A.x} x2={A.x} y1={0} y2={plotH} stroke={col} strokeWidth={sw} /><text x={A.x + 4} y={12} fill={col} fontSize={10.5}>{fmtT(d.a.t, !!intraday)}</text></g>;
    if (d.kind === "note" && A) return (
      <g key={key}><circle cx={A.x} cy={A.y} r={3.5} fill={col} /><rect x={A.x + 6} y={A.y - 20} rx={4} height={18} width={8 + (d.text?.length ?? 0) * 6.6} fill={alpha(cols.yellow, 0.18)} stroke={alpha(cols.yellow, 0.6)} /><text x={A.x + 10} y={A.y - 7} fill={cols.fg1} fontSize={11}>{d.text}</text></g>
    );
    if (!A || !B) return null;
    if (d.kind === "trend" || d.kind === "ray") {
      let bx: number = B.x, by: number = B.y;
      if (d.kind === "ray" && (B.x !== A.x || B.y !== A.y)) { const k = 4000 / Math.hypot(B.x - A.x, B.y - A.y); bx = A.x + (B.x - A.x) * k; by = A.y + (B.y - A.y) * k; }
      return <g key={key}><line x1={A.x} y1={A.y} x2={bx} y2={by} stroke={col} strokeWidth={sw} /><circle cx={A.x} cy={A.y} r={3} fill={cols.panel} stroke={col} /><circle cx={B.x} cy={B.y} r={3} fill={cols.panel} stroke={col} /></g>;
    }
    if (d.kind === "rect") return <rect key={key} x={Math.min(A.x, B.x)} y={Math.min(A.y, B.y)} width={Math.abs(B.x - A.x)} height={Math.abs(B.y - A.y)} fill={alpha(cols.blue, 0.1)} stroke={col} strokeWidth={sw} />;
    if (d.kind === "fib") {
      const x0 = Math.min(A.x, B.x), x1 = Math.max(A.x, B.x);
      return (
        <g key={key}>
          <line x1={A.x} y1={A.y} x2={B.x} y2={B.y} stroke={alpha(col, 0.5)} strokeDasharray="3 3" />
          {FIB.map((f, i) => {
            const y = A.y + (B.y - A.y) * f;
            const price = d.a.p + (d.b!.p - d.a.p) * f;
            const fc = [cols.fg3, cols.down, cols.orange, cols.yellow, cols.up, cols.blue, cols.fg3][i];
            return <g key={f}><line x1={x0} x2={x1} y1={y} y2={y} stroke={fc} strokeWidth={1.2} /><text x={x0 + 4} y={y - 3} fill={fc} fontSize={10}>{f} ({fmtP(price)})</text></g>;
          })}
        </g>
      );
    }
    if (d.kind === "measure") {
      const dp = d.b!.p - d.a.p, pc = dp / d.a.p;
      const nb = Math.round(Math.abs(tToL(d.b!.t) - tToL(d.a.t)));
      const up = dp >= 0, c = up ? cols.up : cols.down;
      const lx = (A.x + B.x) / 2, ly = Math.min(A.y, B.y) - 8;
      return (
        <g key={key}>
          <rect x={Math.min(A.x, B.x)} y={Math.min(A.y, B.y)} width={Math.abs(B.x - A.x)} height={Math.abs(B.y - A.y)} fill={alpha(c, 0.14)} stroke={alpha(c, 0.7)} />
          <rect x={lx - 78} y={ly - 34} width={156} height={34} rx={5} fill={c} />
          <text x={lx} y={ly - 20} textAnchor="middle" fill="#fff" fontSize={11} fontWeight={600}>{(up ? "+" : "") + fmtP(dp)} ({(up ? "+" : "") + (pc * 100).toFixed(2)}%)</text>
          <text x={lx} y={ly - 6} textAnchor="middle" fill="#fff" fontSize={10.5}>{nb} bars · {fmtT(d.a.t, !!intraday).split(",")[0]} → {fmtT(d.b!.t, !!intraday).split(",")[0]}</text>
        </g>
      );
    }
    return null;
  };

  const at = hover ? hover.i : data.length - 1;
  const bar = data[at];
  const prev = data[at - 1];
  const chg = bar && prev ? bar.c! / prev.c! - 1 : null;
  const ic = indColors(cols);
  const v = (arr: (number | null)[] | null | undefined) => (arr && isNum(arr[at]) ? arr[at]! : null);
  const legendInd: [string, string, number | null][] = [
    ...(["sma20", "sma50", "sma200", "ema9", "ema21"] as const).filter((x) => prefs.ind[x]).map((x) => [INDS.find((i) => i.id === x)!.label, ic[x], v(calc[x])] as [string, string, number | null]),
    ...(calc.bb ? [["BB 20,2", ic.bb, v(calc.bb.mid)] as [string, string, number | null]] : []),
    ...(calc.vwap ? [["VWAP", ic.vwap, v(calc.vwap)] as [string, string, number | null]] : []),
  ];
  const tipLeft = hover && hover.x > W - 220;
  const showTip = prefs.tooltip && hover && hover.x >= 0 && tool === "cursor" && !menu;
  const tipTop = hover && hover.y > plotH - 140;
  const curType = TYPES.find((t) => t.id === prefs.type)!;
  const activeInds = INDS.filter((i) => prefs.ind[i.id]).length;

  return (
    <div className="tc" ref={root} tabIndex={0} onKeyDown={onKey} style={{ height }}>
      <div className="tc-bar">
        <div className="tc-dd">
          <button className={`tc-btn ${open === "type" ? "on" : ""}`} onClick={() => setOpen(open === "type" ? null : "type")} title="Chart type">
            <Glyph name={prefs.type} /><span>{curType.label}</span><Icon name="chevron-down" className="xs" />
          </button>
          {open === "type" && (
            <div className="tc-drop">
              {TYPES.map((t) => <button key={t.id} className={prefs.type === t.id ? "on" : ""} onClick={() => { setPrefs({ type: t.id }); setOpen(null); }}><Glyph name={t.id} />{t.label}</button>)}
            </div>
          )}
        </div>
        <div className="tc-dd">
          <button className={`tc-btn ${open === "ind" ? "on" : ""}`} onClick={() => setOpen(open === "ind" ? null : "ind")} title="Indicators and their formulas">
            <span className="fx">ƒx</span><span>Indicators</span>{activeInds > 0 && <span className="n">{activeInds}</span>}<Icon name="chevron-down" className="xs" />
          </button>
          {open === "ind" && (
            <div className="tc-drop wide">
              <div className="tc-dh">Overlays</div>
              {INDS.filter((i) => !i.pane).map((i) => <IndRow key={i.id} i={i} on={prefs.ind[i.id]} color={i.id === "volume" ? cols.fg3 : ic[i.id]} disabled={i.id === "vwap" && !intraday}
                onToggle={() => setPrefs({ ind: { ...prefs.ind, [i.id]: !prefs.ind[i.id] } })} />)}
              <div className="tc-dh">Panes</div>
              {INDS.filter((i) => i.pane).map((i) => <IndRow key={i.id} i={i} on={prefs.ind[i.id]} color={ic[i.id]} onToggle={() => setPrefs({ ind: { ...prefs.ind, [i.id]: !prefs.ind[i.id] } })} />)}
            </div>
          )}
        </div>
        <div className="seg sm">
          {(["auto", "log", "pct"] as Scale[]).map((s) => <button key={s} className={prefs.scale === s ? "on" : ""} onClick={() => setPrefs({ scale: s })} title={s === "auto" ? "Price scale" : s === "log" ? "Logarithmic scale" : "Percent change from the first bar"}>{s === "auto" ? "₹" : s === "log" ? "Log" : "%"}</button>)}
        </div>
        <button className={`tc-btn icon ${prefs.tooltip ? "on" : ""}`} title="Hover panel" onClick={() => setPrefs({ tooltip: !prefs.tooltip })}><Icon name="preview" className="sm" /></button>
        <span className="spacer" />
        <button className="tc-btn icon" title="Undo last drawing (Ctrl+Z)" disabled={!drawings.length} onClick={() => setDrawings((cur) => cur.slice(0, -1))}><Icon name="discard" className="sm" /></button>
        <button className="tc-btn icon" title={`Remove all drawings (${drawings.length})`} disabled={!drawings.length} onClick={() => setDrawings(() => [])}><Icon name="trash" className="sm" /></button>
        <button className="tc-btn icon" title="Reset view" onClick={reset}><Icon name="screen-normal" className="sm" /></button>
        <button className="tc-btn icon" title="Save as image" onClick={snapshot}><Icon name="device-camera" className="sm" /></button>
        <ExportButton title={`${title ?? ticker} chart`} canvas={compose} className="tc-btn icon" />
        <button className="tc-btn icon" title="Fullscreen" onClick={fullscreen}><Icon name={document.fullscreenElement ? "screen-normal" : "screen-full"} className="sm" /></button>
      </div>
      <div className="tc-body">
        <div className="tc-tools" role="toolbar" aria-label="Drawing tools">
          {TOOLS.map((t) => (
            <button key={t.id} className={tool === t.id ? "on" : ""} title={t.label + (t.key ? ` (${t.key})` : "")} onClick={() => { setTool(t.id); setDraft(null); root.current?.focus(); }}>
              <Glyph name={t.id} />
            </button>
          ))}
          <i />
          <button className={prefs.magnet ? "on" : ""} title="Magnet: snap to open, high, low or close" onClick={() => setPrefs({ magnet: !prefs.magnet })}><Glyph name="magnet" /></button>
        </div>
        <div className="tc-area">
        <div ref={area} className={`tc-main tool-${tool}`} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onContextMenu={onContext} onPointerLeave={() => setHover(null)}>
          <div ref={box} className="tc-canvas" />
          <svg ref={svg} className="tc-svg" xmlns="http://www.w3.org/2000/svg" width={W} height={H} style={{ fontFamily: "Inter, sans-serif" }}>
            <defs><clipPath id={`clip-${ticker.replace(/\W/g, "")}`}><rect x={0} y={0} width={plotW} height={plotH} /></clipPath></defs>
            <g clipPath={`url(#clip-${ticker.replace(/\W/g, "")})`}>
              {drawings.map((d) => draw(d))}
              {draft && draw({ kind: draft.kind, a: draft.a, b: draft.b }, true)}
              {measure && draw({ kind: "measure", a: measure.a, b: measure.b })}
            </g>
          </svg>
          {bar && (
            <div className="tc-legend">
              <div className="row1">
                <b>{title ?? ticker}</b>
                <span>O <em>{fmtP(bar.o)}</em></span><span>H <em>{fmtP(bar.h)}</em></span><span>L <em>{fmtP(bar.l)}</em></span><span>C <em>{fmtP(bar.c)}</em></span>
                {isNum(chg) && <span className={chg >= 0 ? "up" : "down"}>{chg >= 0 ? "+" : ""}{(chg * 100).toFixed(2)}%</span>}
                {bar.v > 0 && <span>Vol <em>{fmtV(bar.v)}</em></span>}
              </div>
              {legendInd.length > 0 && <div className="row2">{legendInd.map(([n, c, val]) => <span key={n} style={{ color: c }}>{n} <em>{fmtP(val)}</em></span>)}</div>}
            </div>
          )}
          {showTip && bar && (
            <div className="tc-tip" style={{ left: tipLeft ? hover!.x - 196 : hover!.x + 16, top: tipTop ? hover!.y - 128 : hover!.y + 16 }}>
              <div className="t">{fmtT(bar.t, !!intraday)}</div>
              <div className="g">
                <span>Open</span><b>{fmtP(bar.o)}</b><span>High</span><b>{fmtP(bar.h)}</b>
                <span>Low</span><b>{fmtP(bar.l)}</b><span>Close</span><b>{fmtP(bar.c)}</b>
                <span>Change</span><b className={isNum(chg) ? (chg >= 0 ? "up" : "down") : ""}>{isNum(chg) ? `${chg >= 0 ? "+" : ""}${(chg * 100).toFixed(2)}%` : "—"}</b>
                {bar.v > 0 && <><span>Volume</span><b>{bar.v.toLocaleString("en-IN")}</b></>}
              </div>
            </div>
          )}
          {draft?.waiting && <div className="tc-hint">Click the second point · Esc to cancel</div>}
          {tool !== "cursor" && !draft && <div className="tc-hint">{TOOLS.find((t) => t.id === tool)?.label}: {tool === "eraser" ? "click a drawing to remove it" : tool === "note" ? "click where the note goes" : tool === "hline" || tool === "vline" ? "click to place" : "drag, or click two points"} · Esc to cancel</div>}
          {note && (
            <input className="tc-note inp sm" autoFocus style={{ left: note.x + 8, top: note.y - 14 }} placeholder="Note, then Enter" value={note.text} maxLength={80}
              onChange={(e) => setNote({ ...note, text: e.target.value })}
              onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Enter" && note.text.trim()) { add({ kind: "note", a: note.pt, text: note.text.trim() }); setNote(null); } else if (e.key === "Escape") setNote(null); }}
              onBlur={() => { if (note.text.trim()) add({ kind: "note", a: note.pt, text: note.text.trim() }); setNote(null); }} />
          )}
          {menu && (
            <ContextMenu x={menu.x + (box.current?.getBoundingClientRect().left ?? 0)} y={menu.y + (box.current?.getBoundingClientRect().top ?? 0)}>
              <div className="tc-mh">{fmtP(menu.pt.p)} · {fmtT(menu.pt.t, !!intraday)}</div>
              <button onClick={() => { add({ kind: "hline", a: menu.pt }); setMenu(null); }}><Glyph name="hline" />Horizontal line at {fmtP(menu.pt.p)}</button>
              <button onClick={() => { add({ kind: "vline", a: menu.pt }); setMenu(null); }}><Glyph name="vline" />Vertical line here</button>
              <button onClick={() => { setNote({ pt: menu.pt, x: menu.x, y: menu.y, text: "" }); setMenu(null); }}><Glyph name="note" />Add a note here</button>
              {onAlert && bar && (
                <button onClick={() => { onAlert(menu.pt.p < bar.c! ? "below" : "above", Math.round(menu.pt.p * 100) / 100); setMenu(null); }}>
                  <Icon name="bell" className="sm" />Alert me if the price {menu.pt.p < bar.c! ? "falls" : "rises"} to {fmtP(menu.pt.p)}
                </button>
              )}
              <button onClick={() => { navigator.clipboard?.writeText(menu.pt.p.toFixed(2)); setMenu(null); }}><Icon name="copy" className="sm" />Copy price {fmtP(menu.pt.p)}</button>
              <hr />
              {menu.hit && <button className="danger" onClick={() => { setDrawings((cur) => cur.filter((d) => d.id !== menu.hit)); setMenu(null); }}><Icon name="close" className="sm" />Delete this drawing</button>}
              <button disabled={!drawings.length} onClick={() => { setDrawings(() => []); setMenu(null); }}><Icon name="trash" className="sm" />Remove all drawings ({drawings.length})</button>
              <button onClick={() => { reset(); setMenu(null); }}><Icon name="screen-normal" className="sm" />Reset chart view</button>
              <hr />
              {(["auto", "log", "pct"] as Scale[]).map((s) => (
                <button key={s} onClick={() => { setPrefs({ scale: s }); setMenu(null); }}><Icon name={prefs.scale === s ? "check" : "blank"} className="sm" />{s === "auto" ? "Regular scale" : s === "log" ? "Logarithmic scale" : "Percent scale"}</button>
              ))}
              <button onClick={() => { setPrefs({ ind: { ...prefs.ind, volume: !prefs.ind.volume } }); setMenu(null); }}><Icon name={prefs.ind.volume ? "check" : "blank"} className="sm" />Volume</button>
              <button onClick={() => { setPrefs({ tooltip: !prefs.tooltip }); setMenu(null); }}><Icon name={prefs.tooltip ? "check" : "blank"} className="sm" />Hover panel</button>
              <hr />
              <button onClick={() => { snapshot(); setMenu(null); }}><Icon name="device-camera" className="sm" />Save chart as image</button>
              <button onClick={() => { fullscreen(); setMenu(null); }}><Icon name="screen-full" className="sm" />Fullscreen</button>
            </ContextMenu>
          )}
        </div>
        {panes.map((id) => (
          <div key={id} className="tc-pane" onContextMenu={(e) => e.preventDefault()}>
            <div ref={(el) => { paneBoxes.current[id] = el; }} className="tc-canvas" />
            <div className="tc-plabel">
              {id === "rsi"
                ? <><b>RSI 14</b><em style={{ color: ic.rsi }}>{fmtP(v(calc.rsi), 1)}</em></>
                : <><b>MACD 12 26 9</b><em style={{ color: ic.macd }}>{fmtP(v(calc.macd?.line ?? null))}</em><em style={{ color: ic.signal }}>{fmtP(v(calc.macd?.signal ?? null))}</em><em className={(v(calc.macd?.hist ?? null) ?? 0) >= 0 ? "up" : "down"}>{fmtP(v(calc.macd?.hist ?? null))}</em></>}
            </div>
            <button className="tc-pclose" title="Remove this pane" onClick={() => setPrefs({ ind: { ...prefs.ind, [id]: false } })}><Icon name="close" className="xs" /></button>
          </div>
        ))}
        </div>
      </div>
    </div>
  );
}

/** Fixed to the viewport (x, y are client coordinates) so a short chart pane never clips it. */
function ContextMenu({ x, y, children }: { x: number; y: number; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });
  useEffect(() => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    setPos({ left: x + r.width > innerWidth - 4 ? Math.max(4, x - r.width) : x, top: y + r.height > innerHeight - 4 ? Math.max(4, innerHeight - r.height - 4) : y });
  }, [x, y]);
  return <div ref={ref} className="tc-menu" style={pos} onContextMenu={(e) => e.preventDefault()} onPointerDown={(e) => e.stopPropagation()}>{children}</div>;
}

function IndRow({ i, on, color, onToggle, disabled }: { i: (typeof INDS)[number]; on: boolean; color: string; onToggle: () => void; disabled?: boolean }) {
  return (
    <label className={`tc-ind ${disabled ? "off" : ""}`} title={disabled ? "VWAP needs intraday bars (1D, 5D or 1M)" : undefined}>
      <input type="checkbox" className="cb" checked={on} disabled={disabled} onChange={onToggle} />
      <span className="sw" style={{ background: color }} />
      <span className="grow"><b>{i.label}</b><small>{i.formula}</small></span>
    </label>
  );
}

/** Small line icons for chart types and drawing tools. */
function Glyph({ name }: { name: string }) {
  const p = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.3, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (name) {
    case "candle": return <svg {...p}><path d="M4.5 2v2.5M4.5 10v3M11.5 3v2M11.5 11v2.5" /><rect x="3" y="4.5" width="3" height="5.5" fill="currentColor" /><rect x="10" y="5" width="3" height="6" /></svg>;
    case "hollow": return <svg {...p}><path d="M4.5 2v2.5M4.5 10v3M11.5 3v2M11.5 11v2.5" /><rect x="3" y="4.5" width="3" height="5.5" /><rect x="10" y="5" width="3" height="6" /></svg>;
    case "heikin": return <svg {...p}><path d="M4.5 3v2M4.5 11v2M11.5 2v2M11.5 9v3" /><rect x="3" y="5" width="3" height="6" rx="1" fill="currentColor" /><rect x="10" y="4" width="3" height="5" rx="1" fill="currentColor" /></svg>;
    case "bar": return <svg {...p}><path d="M5 2.5v10M3 5h2M5 10h2M11 4v9.5M9 7h2M11 11h2" /></svg>;
    case "line": return <svg {...p}><path d="M1.5 12l4-5 3 3 6-7" /></svg>;
    case "area": return <svg {...p}><path d="M1.5 12l4-5 3 3 6-7v11h-13z" fill="currentColor" fillOpacity=".25" /><path d="M1.5 12l4-5 3 3 6-7" /></svg>;
    case "baseline": return <svg {...p}><path d="M1 8.5h14" strokeDasharray="1.5 1.5" /><path d="M1.5 11l3-5 3 4 3-7 4 6" /></svg>;
    case "cursor": return <svg {...p}><path d="M8 1.5v4M8 10.5v4M1.5 8h4M10.5 8h4" /><circle cx="8" cy="8" r="1" fill="currentColor" /></svg>;
    case "trend": return <svg {...p}><path d="M3 13L13 3" /><circle cx="3" cy="13" r="1.5" /><circle cx="13" cy="3" r="1.5" /></svg>;
    case "ray": return <svg {...p}><path d="M3 13L15 1" /><circle cx="3" cy="13" r="1.5" /><circle cx="8" cy="8" r="1.5" /></svg>;
    case "hline": return <svg {...p}><path d="M1 8h14" /><circle cx="8" cy="8" r="1.5" /></svg>;
    case "vline": return <svg {...p}><path d="M8 1v14" /><circle cx="8" cy="8" r="1.5" /></svg>;
    case "rect": return <svg {...p}><rect x="2.5" y="4" width="11" height="8" /></svg>;
    case "fib": return <svg {...p}><path d="M2 3h12M2 6.5h12M2 9.5h12M2 13h12" /><path d="M3 13L13 3" strokeDasharray="1.5 1.5" /></svg>;
    case "measure": return <svg {...p}><path d="M2 14L14 2M5 14l-3 0 0-3M11 2h3v3" /><path d="M6 10l1 1M8 8l1 1M10 6l1 1" /></svg>;
    case "note": return <svg {...p}><path d="M3 2.5h10v8H8l-3 3v-3H3z" /><path d="M5.5 5.5h5M5.5 7.5h3" /></svg>;
    case "eraser": return <svg {...p}><path d="M9 3l4 4-6 6H4l-2-2z" /><path d="M6 6l4 4M7 13h7" /></svg>;
    case "magnet": return <svg {...p}><path d="M3 2.5h3v6a2 2 0 0 0 4 0v-6h3v6a5 5 0 0 1-10 0z" /><path d="M3 5h3M10 5h3" /></svg>;
    default: return <svg {...p} />;
  }
}
