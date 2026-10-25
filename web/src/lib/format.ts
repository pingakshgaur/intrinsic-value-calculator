// Null-safe formatters. Every value from the server may be null; none of
// these throw, and all return a printable string.

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function money(v: unknown, digits = 2): string {
  if (!isNum(v)) return "—";
  return "₹" + (digits === 0 || Math.abs(v) >= 100000 ? inr0.format(v) : inr.format(v));
}

export function num(v: unknown, digits = 2): string {
  if (!isNum(v)) return "—";
  return v.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function pct(v: unknown, digits = 1, signed = false): string {
  if (!isNum(v)) return "—";
  const s = (v * 100).toFixed(digits) + "%";
  return signed && v > 0 ? "+" + s : s;
}

/** For values already in percent units (e.g. "MAPE %" = 57.6). */
export function pctUnits(v: unknown, digits = 1): string {
  if (!isNum(v)) return "—";
  return v.toFixed(digits) + "%";
}

export function signed(v: unknown, digits = 2): string {
  if (!isNum(v)) return "—";
  return (v > 0 ? "+" : "") + v.toFixed(digits);
}

export function crore(v: unknown): string {
  if (!isNum(v)) return "—";
  return "₹" + inr0.format(v) + " Cr";
}

export function ago(ts: unknown): string {
  if (!isNum(ts)) return "never";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function when(ts: unknown): string {
  if (!isNum(ts)) return "—";
  return new Date(ts * 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export function isoWhen(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export function duration(sec: unknown): string {
  if (!isNum(sec)) return "—";
  if (sec < 60) return `${Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  return `${m}m ${Math.round(sec - m * 60)}s`;
}

export function bytes(n: unknown): string {
  if (!isNum(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

export function titleCase(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bLlm\b/g, "LLM")
    .replace(/\bPe\b/g, "P/E")
    .replace(/\bEv\b/g, "EV");
}

export function shortName(name: string): string {
  return name.replace(/\s+(Limited|Ltd\.?|Corporation|Company)$/i, "");
}

export const slug = (s: string) => encodeURIComponent(s);
