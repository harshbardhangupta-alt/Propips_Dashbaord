import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorBox, Notice, Spinner } from "./ui";

/** Optional AI explanation, displayed separately from the deterministic calculations. */
export function ExplainButton({ kind, signalId, symbol }: { kind: "D2_SIGNAL" | "D1_MTF"; signalId?: number; symbol?: string }) {
  const m = useMutation({ mutationFn: () => api("/api/system/explain", { body: { kind, signal_id: signalId, symbol } }) });
  return (
    <div className="space-y-2">
      <button className="btn-ghost btn-sm" onClick={() => m.mutate()} disabled={m.isPending}>{m.isPending ? <Spinner label="Asking AI…" /> : "Explain with AI (optional)"}</button>
      {m.isError && <ErrorBox error={m.error} />}
      {m.data && !m.data.available && <Notice tone="muted">AI unavailable: {m.data.status} — {m.data.message}</Notice>}
      {m.data?.available && (
        <div className="rounded-lg border border-ink-line bg-ink-raised p-3">
          <div className="mb-1 flex items-center justify-between"><span className="label">AI explanation · {m.data.model}</span></div>
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-fg-muted">{m.data.text}</div>
          {m.data.warnings?.length > 0 && <div className="mt-2 space-y-1">{m.data.warnings.map((w: string) => <div key={w} className="text-xs text-warn">⚠ {w}</div>)}</div>}
          <div className="mt-2 text-[11px] text-fg-faint">{m.data.disclaimer}</div>
        </div>
      )}
    </div>
  );
}
