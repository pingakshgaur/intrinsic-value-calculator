// Technical indicators for the price chart. Every function returns an array
// aligned with its input (null during the warm-up), so the chart can pair
// values with bar times by index.
import { Bar } from "./live";

type Series = (number | null)[];

export function sma(v: number[], n: number): Series {
  const out: Series = [];
  let sum = 0;
  for (let i = 0; i < v.length; i++) {
    sum += v[i];
    if (i >= n) sum -= v[i - n];
    out.push(i >= n - 1 ? sum / n : null);
  }
  return out;
}

export function ema(v: number[], n: number): Series {
  const out: Series = [];
  const k = 2 / (n + 1);
  let prev: number | null = null;
  for (let i = 0; i < v.length; i++) {
    if (i < n - 1) { out.push(null); continue; }
    prev = prev == null ? v.slice(0, n).reduce((a, b) => a + b, 0) / n : v[i] * k + prev * (1 - k);
    out.push(prev);
  }
  return out;
}

export function bollinger(v: number[], n = 20, mult = 2) {
  const mid = sma(v, n);
  const up: Series = [], lo: Series = [];
  for (let i = 0; i < v.length; i++) {
    const m = mid[i];
    if (m == null) { up.push(null); lo.push(null); continue; }
    const w = v.slice(i - n + 1, i + 1);
    const sd = Math.sqrt(w.reduce((a, x) => a + (x - m) ** 2, 0) / n);
    up.push(m + mult * sd);
    lo.push(m - mult * sd);
  }
  return { mid, up, lo };
}

/** Wilder's RSI. */
export function rsi(v: number[], n = 14): Series {
  const out: Series = [null];
  let gain = 0, loss = 0;
  for (let i = 1; i < v.length; i++) {
    const d = v[i] - v[i - 1];
    const g = Math.max(d, 0), l = Math.max(-d, 0);
    if (i <= n) {
      gain += g; loss += l;
      if (i < n) { out.push(null); continue; }
      gain /= n; loss /= n;
    } else {
      gain = (gain * (n - 1) + g) / n;
      loss = (loss * (n - 1) + l) / n;
    }
    out.push(loss === 0 ? 100 : 100 - 100 / (1 + gain / loss));
  }
  return out;
}

export function macd(v: number[], fast = 12, slow = 26, signal = 9) {
  const f = ema(v, fast), s = ema(v, slow);
  const line: Series = v.map((_, i) => (f[i] != null && s[i] != null ? f[i]! - s[i]! : null));
  const start = line.findIndex((x) => x != null);
  const sig: Series = v.map(() => null);
  if (start >= 0) {
    const e = ema(line.slice(start) as number[], signal);
    e.forEach((x, i) => { sig[start + i] = x; });
  }
  const hist: Series = line.map((x, i) => (x != null && sig[i] != null ? x - sig[i]! : null));
  return { line, signal: sig, hist };
}

/** Volume-weighted average price, restarting every Indian trading day. */
export function vwap(bars: Bar[]): Series {
  let pv = 0, vol = 0, day = "";
  return bars.map((b) => {
    const d = new Date((b.t + 19800) * 1000).toISOString().slice(0, 10);
    if (d !== day) { day = d; pv = 0; vol = 0; }
    const tp = ((b.h ?? 0) + (b.l ?? 0) + (b.c ?? 0)) / 3;
    pv += tp * (b.v || 0);
    vol += b.v || 0;
    return vol ? pv / vol : null;
  });
}

export function heikinAshi(bars: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (const b of bars) {
    const c = ((b.o ?? 0) + (b.h ?? 0) + (b.l ?? 0) + (b.c ?? 0)) / 4;
    const p = out[out.length - 1];
    const o = p ? (p.o! + p.c!) / 2 : ((b.o ?? 0) + (b.c ?? 0)) / 2;
    out.push({ t: b.t, o, c, h: Math.max(b.h ?? c, o, c), l: Math.min(b.l ?? c, o, c), v: b.v });
  }
  return out;
}
