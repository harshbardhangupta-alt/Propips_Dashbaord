export const PAPER_BANNER = "PAPER TRADING ONLY — NO LIVE ORDERS";

export function PaperBadge() {
  return (
    <div role="status" aria-label={PAPER_BANNER} className="inline-flex items-center gap-2 rounded-md border border-neon/40 bg-neon-dim px-2.5 py-1 text-[11px] font-semibold tracking-[0.08em] text-neon">
      <span className="h-1.5 w-1.5 rounded-full bg-neon" />
      {PAPER_BANNER}
    </div>
  );
}
