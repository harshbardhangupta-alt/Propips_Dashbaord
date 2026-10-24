const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export const money = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `₹${digits === 0 ? inr0.format(v) : inr.format(v)}`;
export const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "—" : inr.format(Number(v.toFixed(d))));
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);
export const signed = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${inr.format(v)}`);
export const tone = (v: number | null | undefined) => (v === null || v === undefined || v === 0 ? "text-fg-muted" : v > 0 ? "text-up" : "text-down");

export function time(iso: string | null | undefined, withDate = true) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour12: false, ...(withDate ? { day: "2-digit", month: "short" } : {}), hour: "2-digit", minute: "2-digit" });
}

export function ago(iso: string | null | undefined) {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return `${Math.max(0, Math.round(s))}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** Client-side mirror of the backend formula, for display hints only. The backend is authoritative. */
export function rr(entry: number, stop: number, target: number) {
  const risk = entry - stop;
  return risk > 0 ? (target - entry) / risk : NaN;
}
