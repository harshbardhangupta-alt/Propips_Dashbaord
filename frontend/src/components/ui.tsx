import { ReactNode, useEffect } from "react";

export function Panel({ title, actions, children, className = "", pad = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 px-5 pt-4 pb-3 border-b border-ink-line/70">
          <h2 className="text-sm font-semibold tracking-tight text-fg">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={pad ? "panel-pad" : ""}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, toneClass = "" }: { label: string; value: ReactNode; hint?: ReactNode; toneClass?: string }) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className={`mt-1 num text-lg text-fg ${toneClass}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-fg-faint truncate">{hint}</div>}
    </div>
  );
}

const TONES: Record<string, string> = {
  good: "text-up border-up/25 bg-up-dim",
  bad: "text-down border-down/25 bg-down-dim",
  warn: "text-warn border-warn/25 bg-warn-dim",
  neon: "text-neon border-neon/30 bg-neon-dim",
  muted: "text-fg-muted border-ink-line bg-white/[0.02]",
};

const STATUS_TONE: Record<string, keyof typeof TONES> = {
  BULLISH: "good", CONFIRMED: "good", MOMENTUM_UP: "good", QUALIFIED: "good", CONNECTED: "good", SUCCESS: "good", OPEN: "neon", VALID: "good",
  FRESH: "good", RECENT_SNAPSHOT: "good", MAPPED: "good", OK: "good", CLOSED: "muted", TAKE_PROFIT: "good", TAKE_PROFIT_GAP: "good",
  BEARISH: "bad", NOT_CONFIRMED: "bad", REJECTED: "bad", FAILED: "bad", AUTH_FAILED: "bad", PERMISSION_DENIED: "bad", INVALIDATED: "bad",
  STOP_LOSS: "bad", STOP_LOSS_GAP: "bad", ERROR: "bad", NETWORK_ERROR: "bad", MISSING_IN_SCRIP_MASTER: "bad", STALE: "warn",
  NEUTRAL: "warn", PARTIAL: "warn", WAITING: "warn", PENDING_ENTRY: "neon", CONFIGURED: "warn", RATE_LIMITED: "warn", UNTESTED: "warn",
  DELAYED_SNAPSHOT: "warn", LAST_AVAILABLE: "muted", EXPIRED: "muted", CANCELLED: "muted", TRIGGERED: "neon", RUNNING: "neon",
  UNAVAILABLE: "muted", NOT_EVALUATED: "muted", NOT_CONFIGURED: "muted", NO_DATA: "muted", SKIPPED: "muted", DISABLED: "muted",
  MARKET_DATA_UNAVAILABLE: "bad", QUOTA_EXCEEDED: "bad", MANUAL_EXIT: "muted", UNMAPPED: "warn",
};

export function Pill({ value, tone, children, title }: { value?: string | null; tone?: keyof typeof TONES; children?: ReactNode; title?: string }) {
  const t = tone ?? STATUS_TONE[value ?? ""] ?? "muted";
  return (
    <span title={title} className={`chip ${TONES[t]}`}>
      {children ?? (value ? value.replace(/_/g, " ") : "—")}
    </span>
  );
}

export function Modal({ open, onClose, title, children, wide = false }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 backdrop-blur-sm p-4 md:p-8" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" className={`panel w-full ${wide ? "max-w-6xl" : "max-w-xl"} bg-ink-panel/95`}>
        <header className="flex items-center justify-between gap-3 px-6 pt-5 pb-4 border-b border-ink-line">
          <div className="min-w-0">{title}</div>
          <button className="btn-ghost btn-sm" onClick={onClose} aria-label="Close">Esc</button>
        </header>
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}

export function Field({ label, hint, children, error }: { label: string; hint?: ReactNode; children: ReactNode; error?: string | null }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <div className="mt-1.5">{children}</div>
      {error ? <span className="mt-1 block text-xs text-down">{error}</span> : hint ? <span className="mt-1 block text-xs text-fg-faint">{hint}</span> : null}
    </label>
  );
}

export function Notice({ tone = "muted", children }: { tone?: "muted" | "warn" | "bad" | "good" | "neon"; children: ReactNode }) {
  return <div className={`rounded-lg border px-3.5 py-2.5 text-sm ${TONES[tone]}`}>{children}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-fg-muted">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-fg-faint border-t-neon" />
      {label}
    </span>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="py-14 text-center">
      <div className="text-sm font-medium text-fg">{title}</div>
      {children && <div className="mt-1.5 text-sm text-fg-muted max-w-lg mx-auto">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <Notice tone="bad">{msg}</Notice>;
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: ReactNode }[] }) {
  return (
    <div className="inline-flex gap-1 rounded-lg border border-ink-line bg-ink p-1">
      {items.map((i) => (
        <button key={i.id} className={`tab ${value === i.id ? "tab-active" : ""}`} onClick={() => onChange(i.id)}>
          {i.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-fg-muted select-none">
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 rounded-full border transition ${checked ? "bg-neon/90 border-neon" : "bg-ink border-ink-line"}`}>
        <span className={`absolute top-0.5 h-3.5 w-3.5 rounded-full transition ${checked ? "left-[18px] bg-ink" : "left-0.5 bg-fg-faint"}`} />
      </button>
      {label}
    </label>
  );
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto,1fr] gap-x-6 gap-y-1.5 text-sm">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-fg-faint">{k}</dt>
          <dd className="num text-right text-fg">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
