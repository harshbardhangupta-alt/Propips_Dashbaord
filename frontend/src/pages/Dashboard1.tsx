import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { AccountStrip } from "../components/AccountStrip";
import { AutoTradeModalD1 } from "../components/AutoTradeModalD1";
import { Empty, ErrorBox, Notice, Panel, Pill, Spinner, Toggle } from "../components/ui";
import { ago, money, num, pct, signed, tone } from "../lib/format";

type Row = any;
type SortKey = "symbol" | "price" | "change" | "pct" | "quality" | "pnl";

export default function Dashboard1() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["d1-stocks"], queryFn: () => api("/api/d1/stocks"), refetchInterval: 20_000 });
  const refresh = useMutation({ mutationFn: () => api("/api/d1/refresh-mtf", { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["d1-stocks"] }) });
  const [search, setSearch] = useState("");
  const [bias, setBias] = useState("ALL");
  const [conf, setConf] = useState("ALL");
  const [onlyEnabled, setOnlyEnabled] = useState(false);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [sort, setSort] = useState<SortKey>("symbol");
  const [dir, setDir] = useState<1 | -1>(1);
  const [selected, setSelected] = useState<Row | null>(null);

  const rows: Row[] = q.data?.stocks ?? [];
  const view = useMemo(() => {
    const s = search.trim().toUpperCase();
    const out = rows.filter((r) => {
      if (s && !r.symbol.includes(s) && !r.company_name.toUpperCase().includes(s)) return false;
      if (bias !== "ALL" && r.bias !== bias) return false;
      if (conf !== "ALL" && r.confirmation !== conf) return false;
      if (onlyEnabled && !r.trade) return false;
      if (onlyOpen && r.position_status !== "OPEN") return false;
      return true;
    });
    const key = (r: Row): number | string => {
      switch (sort) {
        case "symbol": return r.symbol;
        case "price": return r.quote?.ltp ?? -Infinity;
        case "change": return r.quote?.change ?? -Infinity;
        case "pct": return r.quote?.pct_change ?? -Infinity;
        case "quality": return r.quality ?? 0;
        case "pnl": return r.unrealized_pnl ?? -Infinity;
      }
    };
    return [...out].sort((a, b) => {
      const x = key(a), y = key(b);
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
  }, [rows, search, bias, conf, onlyEnabled, onlyOpen, sort, dir]);

  const reset = () => { setSearch(""); setBias("ALL"); setConf("ALL"); setOnlyEnabled(false); setOnlyOpen(false); setSort("symbol"); setDir(1); };
  const th = (k: SortKey, label: string, right = false) => (
    <th className={right ? "text-right" : ""}>
      <button className={`inline-flex items-center gap-1 hover:text-fg ${sort === k ? "text-fg" : ""}`} onClick={() => (sort === k ? setDir((d) => (d === 1 ? -1 : 1)) : (setSort(k), setDir(k === "symbol" ? 1 : -1)))}>
        {label}{sort === k ? (dir === 1 ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
  const prog = q.data?.mtf_refresh;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">MTF Paper Trading</h1>
          <p className="mt-1 text-sm text-fg-muted">Dashboard 1 · Nifty 100 · Daily trend → 4H structure → 15m setup → 5m entry. Independent of the Mechanical Swing strategy.</p>
        </div>
        <div className="flex items-center gap-3 text-xs text-fg-faint">
          <span>Universe {q.data?.last_universe_refresh ? `synced ${ago(q.data.last_universe_refresh.at)}` : "not synced"}</span>
          {prog?.running ? <Spinner label={`MTF ${prog.done}/${prog.total}`} /> : prog?.finished_at && <span>MTF refreshed {ago(prog.finished_at)}{prog.errors ? ` · ${prog.errors} errors` : ""}</span>}
          <button className="btn-ghost btn-sm" disabled={refresh.isPending || prog?.running} onClick={() => refresh.mutate()}>Refresh MTF now</button>
        </div>
      </div>
      {refresh.isError && <ErrorBox error={refresh.error} />}
      {prog?.last_error && <Notice tone="warn">Last MTF data error: {prog.last_error}</Notice>}
      <AccountStrip code="D1_MTF" />

      <Panel pad={false}>
        <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-b border-ink-line/70">
          <input className="input !w-64" placeholder="Search symbol or company…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <select className="input !w-auto" value={bias} onChange={(e) => setBias(e.target.value)}>
            <option value="ALL">All MTF bias</option><option value="BULLISH">Bullish</option><option value="NEUTRAL">Neutral</option><option value="BEARISH">Bearish</option><option value="UNAVAILABLE">Unavailable</option>
          </select>
          <select className="input !w-auto" value={conf} onChange={(e) => setConf(e.target.value)}>
            <option value="ALL">Any confirmation</option><option value="CONFIRMED">Confirmed (4/4)</option><option value="PARTIAL">Partial</option><option value="NOT_CONFIRMED">Not confirmed</option><option value="UNAVAILABLE">Unavailable</option>
          </select>
          <Toggle checked={onlyEnabled} onChange={setOnlyEnabled} label="Auto-trade enabled" />
          <Toggle checked={onlyOpen} onChange={setOnlyOpen} label="Open positions" />
          <button className="btn-ghost btn-sm ml-auto" onClick={reset}>Reset filters</button>
          <span className="text-xs text-fg-faint num">{view.length}/{rows.length}</span>
        </div>
        {q.isLoading ? (
          <div className="p-10 text-center"><Spinner label="Loading Nifty 100…" /></div>
        ) : q.isError ? (
          <div className="p-5"><ErrorBox error={q.error} /></div>
        ) : rows.length === 0 ? (
          <Empty title="Nifty 100 universe not loaded">
            Sync the official constituent list and the Dhan scrip master in <Link className="text-neon" to="/settings">Settings → Universes</Link>. No constituents are invented.
          </Empty>
        ) : (
          <div className="table-wrap !rounded-none !border-0 max-h-[68vh]">
            <table className="data">
              <thead>
                <tr>
                  {th("symbol", "Symbol")}<th>Company</th>{th("price", "Price", true)}{th("change", "Chg", true)}{th("pct", "Chg %", true)}
                  <th>Daily</th><th>4H</th><th>15m setup</th><th>5m entry</th>{th("quality", "MTF bias")}<th>Auto trade</th><th>Position</th>{th("pnl", "Unrl. P&L", true)}<th>Data</th><th></th>
                </tr>
              </thead>
              <tbody>
                {view.map((r) => (
                  <tr key={r.symbol}>
                    <td className="font-medium">{r.symbol}{r.mapping_status !== "MAPPED" && <span className="ml-2"><Pill value={r.mapping_status} /></span>}</td>
                    <td className="max-w-[220px] truncate text-fg-muted">{r.company_name}</td>
                    <td className="num text-right">{num(r.quote?.ltp)}</td>
                    <td className={`num text-right ${tone(r.quote?.change)}`}>{signed(r.quote?.change)}</td>
                    <td className={`num text-right ${tone(r.quote?.pct_change)}`}>{pct(r.quote?.pct_change)}</td>
                    <td><Pill value={r.daily_trend} /></td>
                    <td><Pill value={r.h4_trend} /></td>
                    <td><Pill value={r.m15_status} /></td>
                    <td><Pill value={r.m5_status} /></td>
                    <td><span className="flex items-center gap-2"><Pill value={r.bias} /><span className="num text-xs text-fg-faint">{r.quality}/4</span></span></td>
                    <td><Pill value={r.auto_trade_status} /></td>
                    <td><Pill value={r.position_status === "OPEN" ? "OPEN" : "NONE"} tone={r.position_status === "OPEN" ? "neon" : "muted"} /></td>
                    <td className={`num text-right ${tone(r.unrealized_pnl)}`}>{r.unrealized_pnl === null ? "—" : money(r.unrealized_pnl)}</td>
                    <td className="text-xs text-fg-faint">
                      <div><Pill value={r.quote?.data_state} /></div>
                      <div className="mt-0.5">{r.quote?.fetched_at ? ago(r.quote.fetched_at) : "no quote"}</div>
                    </td>
                    <td className="text-right">
                      <button className="btn-primary btn-sm" disabled={!!r.trade || r.mapping_status !== "MAPPED"} title={r.trade ? "An auto trade is already active for this stock (see Paper Trade Book)" : ""} onClick={() => setSelected(r)}>
                        Enable Auto Trade
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {selected && <AutoTradeModalD1 row={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
