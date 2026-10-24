import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { AccountStrip } from "../components/AccountStrip";
import { AutoTradeModalD2 } from "../components/AutoTradeModalD2";
import { Empty, ErrorBox, Notice, Panel, Pill, Spinner, Stat, Tabs, Toggle } from "../components/ui";
import { ago, money, num, pct, time, tone } from "../lib/format";

type View = "qualified" | "rejected" | "all";

export default function Dashboard2() {
  const qc = useQueryClient();
  const [view, setView] = useState<View>("qualified");
  const status = useQuery({ queryKey: ["d2-status"], queryFn: () => api("/api/d2/scanner/status"), refetchInterval: (q) => (q.state.data?.running ? 2000 : 10000) });
  const sigs = useQuery({ queryKey: ["d2-signals", view], queryFn: () => api(`/api/d2/signals?view=${view}`), refetchInterval: 15000 });
  const inv = () => { qc.invalidateQueries({ queryKey: ["d2-status"] }); qc.invalidateQueries({ queryKey: ["d2-signals"] }); };
  const act = useMutation({ mutationFn: (path: string) => api(`/api/d2/scanner/${path}`, { method: "POST" }), onSuccess: inv });
  const toggleAfter = useMutation({ mutationFn: (enabled: boolean) => api("/api/d2/scanner/after-market", { body: { enabled } }), onSuccess: inv });

  const [grade, setGrade] = useState("ALL");
  const [trend, setTrend] = useState("ALL");
  const [minScore, setMinScore] = useState("");
  const [pmin, setPmin] = useState("");
  const [pmax, setPmax] = useState("");
  const [sector, setSector] = useState("ALL");
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [onlyNew, setOnlyNew] = useState(false);
  const [validity, setValidity] = useState("ALL");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [selected, setSelected] = useState<any | null>(null);

  const rows: any[] = sigs.data?.signals ?? [];
  const sectors = useMemo(() => Array.from(new Set(rows.map((r) => r.industry).filter(Boolean))).sort(), [rows]);
  const filtered = rows.filter((r) => {
    const price = r.quote?.ltp ?? r.ltp;
    if (grade !== "ALL" && r.grade !== grade) return false;
    if (trend !== "ALL" && r.daily?.bias !== trend) return false;
    if (minScore && r.score < Number(minScore)) return false;
    if (pmin && (price ?? -1) < Number(pmin)) return false;
    if (pmax && (price ?? Infinity) > Number(pmax)) return false;
    if (sector !== "ALL" && r.industry !== sector) return false;
    if (onlyOpen && r.trade?.status !== "OPEN") return false;
    if (onlyNew && !r.is_new) return false;
    if (validity === "STALE" && !["EXPIRED", "INVALIDATED"].includes(r.validity)) return false;
    if (validity === "VALID" && r.validity !== "VALID") return false;
    return true;
  });
  const reset = () => { setGrade("ALL"); setTrend("ALL"); setMinScore(""); setPmin(""); setPmax(""); setSector("ALL"); setOnlyOpen(false); setOnlyNew(false); setValidity("ALL"); };

  const s = status.data;
  const latest = s?.latest;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Mechanical Swing Scanner</h1>
        <p className="mt-1 text-sm text-fg-muted">Dashboard 2 · Nifty LargeMidcap 250 · Daily 50 EMA · 4H impulse & BOS · 3 red 1H candles · discount &lt; 50% · demand zone · bullish confirmation · min 1:3.</p>
      </div>

      <Panel title="Scanner" actions={
        <>
          {s?.auto_scan_enabled ? (
            <button className="btn-ghost btn-sm" onClick={() => act.mutate("stop")} disabled={act.isPending}>Stop Auto Scan</button>
          ) : (
            <button className="btn-primary btn-sm" onClick={() => act.mutate("start")} disabled={act.isPending}>Start Auto Scan</button>
          )}
          <button className="btn-ghost btn-sm" onClick={() => act.mutate("run-now")} disabled={act.isPending || s?.running}>Run Scan Now</button>
        </>
      }>
        {status.isLoading ? <Spinner /> : status.isError ? <ErrorBox error={status.error} /> : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-5 md:grid-cols-4 xl:grid-cols-8">
              <Stat label="Status" value={<Pill value={s.running ? "RUNNING" : s.auto_scan_enabled ? "OK" : "DISABLED"}>{s.running ? "SCANNING" : s.auto_scan_enabled ? "AUTO SCAN ON" : "AUTO SCAN OFF"}</Pill>} />
              <Stat label="Progress" value={s.running ? `${s.progress.done}/${s.progress.total}` : latest ? `${latest.scanned}/${latest.universe_size}` : "—"} hint={s.running ? s.progress.current : latest ? `last: ${latest.kind}` : ""} />
              <Stat label="Qualified" value={latest?.qualified ?? "—"} toneClass="text-up" />
              <Stat label="Rejected" value={latest?.rejected ?? "—"} hint={latest ? `${latest.unavailable} unavailable · ${latest.errors} errors` : ""} />
              <Stat label="Last successful" value={<span className="text-sm">{time(s.last_successful?.finished_at)}</span>} hint={s.last_successful ? `${s.last_successful.status} · ${ago(s.last_successful.finished_at)}` : "none yet"} />
              <Stat label="Last after-market" value={<span className="text-sm">{time(s.last_after_market?.finished_at)}</span>} hint={s.last_after_market?.status ?? "none yet"} />
              <Stat label="Next scheduled" value={<span className="text-sm">{s.next_regular_scan ? time(s.next_regular_scan) : "auto scan off"}</span>} hint={s.next_after_market_scan ? `after-market ${time(s.next_after_market_scan)}` : "after-market off"} />
              <Stat label="Universe" value={`${s.universe_mapped}/${s.universe_size}`} hint="mapped / constituents" />
            </div>
            {latest && <div className="text-xs text-fg-muted"><Pill value={latest.status} /> <span className="ml-2">Scan #{latest.id} ({latest.kind}{latest.label ? ` · ${latest.label}` : ""}) — {latest.message ?? "running"}</span></div>}
            <div className="flex flex-wrap items-center gap-4 text-xs text-fg-faint">
              <span>{s.schedule}.</span>
              <Toggle checked={s.after_market_enabled} onChange={(v) => toggleAfter.mutate(v)} label="19:00 after-market scan" />
              <span>{s.after_market_note} Scans run only while the backend process is running.</span>
            </div>
            {act.isError && <ErrorBox error={act.error} />}
            {s.universe_size === 0 && <Notice tone="warn">Nifty 250 universe is empty. Sync it in <Link className="text-neon" to="/settings">Settings</Link>.</Notice>}
          </div>
        )}
      </Panel>

      <AccountStrip code="D2_MECH" />

      <Panel pad={false}>
        <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-b border-ink-line/70">
          <Tabs value={view} onChange={(v) => { setView(v); setExpanded(null); }} items={[{ id: "qualified", label: "Qualified BUY setups" }, { id: "rejected", label: "Rejected candidates" }, { id: "all", label: "All" }]} />
          <select className="input !w-auto" value={grade} onChange={(e) => setGrade(e.target.value)}><option value="ALL">All grades</option><option value="A+">A+</option><option value="A">A</option><option value="B">B</option><option value="C">C</option></select>
          <select className="input !w-auto" value={trend} onChange={(e) => setTrend(e.target.value)}><option value="ALL">Any daily trend</option><option value="BULLISH">Bullish</option><option value="NEUTRAL">Neutral</option><option value="BEARISH">Bearish</option></select>
          <input className="input !w-24 num" placeholder="Min score" value={minScore} onChange={(e) => setMinScore(e.target.value)} />
          <input className="input !w-24 num" placeholder="Price ≥" value={pmin} onChange={(e) => setPmin(e.target.value)} />
          <input className="input !w-24 num" placeholder="Price ≤" value={pmax} onChange={(e) => setPmax(e.target.value)} />
          <select className="input !w-auto" value={validity} onChange={(e) => setValidity(e.target.value)}><option value="ALL">Any validity</option><option value="VALID">Valid</option><option value="STALE">Stale / invalidated</option></select>
          {sectors.length > 0 && <select className="input !w-auto max-w-[200px]" value={sector} onChange={(e) => setSector(e.target.value)}><option value="ALL">All sectors</option>{sectors.map((x) => <option key={x}>{x}</option>)}</select>}
          <Toggle checked={onlyNew} onChange={setOnlyNew} label="New" />
          <Toggle checked={onlyOpen} onChange={setOnlyOpen} label="Open positions" />
          <button className="btn-ghost btn-sm ml-auto" onClick={reset}>Reset</button>
          <span className="num text-xs text-fg-faint">{filtered.length}/{rows.length}</span>
        </div>
        {sigs.isLoading ? <div className="p-10 text-center"><Spinner label="Loading signals…" /></div> : sigs.isError ? <div className="p-5"><ErrorBox error={sigs.error} /></div> : filtered.length === 0 ? (
          <Empty title={view === "qualified" ? "No qualified Mechanical Swing setups" : "No candidates"}>
            {rows.length ? "No rows match the filters." : view === "qualified" ? "Run a scan. A setup qualifies only when every mandatory rule passes and the score is ≥ 75 — empty results are normal." : "Run a scan to evaluate the universe."}
          </Empty>
        ) : (
          <div className="table-wrap !rounded-none !border-0 max-h-[70vh]">
            <table className="data">
              <thead><tr>
                <th>Symbol</th><th className="text-right">Price</th><th className="text-right">Chg %</th><th>D 50 EMA</th><th>Daily bias</th><th>4H structure</th><th>Impulse</th><th>Pullback</th><th className="text-right">Retr.</th><th>Demand zone</th><th>Confirm.</th>
                <th className="text-right">Score</th><th>Grade</th><th className="text-right">Entry</th><th className="text-right">Stop</th><th className="text-right">Target</th><th className="text-right">R:R</th><th className="text-right">Qty</th><th className="text-right">Capital</th><th className="text-right">Risk</th><th>Signal time</th><th>Validity</th><th>Paper trade</th><th></th>
              </tr></thead>
              <tbody>
                {filtered.map((r) => {
                  const chk = (rule: string) => r.checks?.find((c: any) => c.rule === rule);
                  const p = (rule: string) => { const c = chk(rule); return c ? <Pill tone={c.passed ? "good" : "bad"} title={c.detail}>{c.passed ? "PASS" : "FAIL"}</Pill> : <Pill value={r.status} />; };
                  return (
                    <Fragment key={r.id}>
                      <tr className="cursor-pointer" onClick={() => setExpanded(expanded === r.id ? null : r.id)}>
                        <td className="font-medium">{r.symbol}{r.is_new && r.status === "QUALIFIED" && <span className="ml-2"><Pill tone="neon">NEW</Pill></span>}{r.after_market && <span className="ml-2"><Pill tone="muted" title={r.after_market_label}>AFTER-MKT</Pill></span>}</td>
                        <td className="num text-right">{num(r.quote?.ltp ?? r.ltp)}</td>
                        <td className={`num text-right ${tone(r.quote?.pct_change)}`}>{pct(r.quote?.pct_change ?? r.pct_change)}</td>
                        <td>{p("A")}</td>
                        <td><Pill value={r.daily?.bias} /></td>
                        <td className="text-xs text-fg-muted">{r.h4?.structure?.replace(/_/g, " ").toLowerCase() ?? "—"}</td>
                        <td>{p("B")}</td>
                        <td>{p("C")}</td>
                        <td className="num text-right">{r.pullback?.retracement_pct != null ? `${r.pullback.retracement_pct}%` : "—"}</td>
                        <td>{p("E")}</td>
                        <td>{p("F")}</td>
                        <td className="num text-right">{r.score.toFixed(0)}</td>
                        <td><Pill tone={r.grade === "A+" || r.grade === "A" ? "good" : "muted"}>{r.grade}</Pill></td>
                        <td className="num text-right">{num(r.entry)}</td>
                        <td className="num text-right">{num(r.stop_loss)}</td>
                        <td className="num text-right">{num(r.target)}</td>
                        <td className="num text-right">{r.reward_risk ? `1:${r.reward_risk}` : "—"}</td>
                        <td className="num text-right">{r.suggested_qty ?? "—"}</td>
                        <td className="num text-right">{r.capital_required != null ? money(r.capital_required, 0) : "—"}</td>
                        <td className="num text-right">{r.planned_risk != null ? money(r.planned_risk, 0) : "—"}</td>
                        <td className="text-xs text-fg-muted">{time(r.confirmation?.time ?? r.evaluated_at)}</td>
                        <td><Pill value={r.status === "QUALIFIED" ? r.validity : r.status} title={r.invalidated_reason ?? (r.valid_until ? `valid until ${time(r.valid_until)}` : "")} /></td>
                        <td>{r.trade ? <Pill value={r.trade.status} /> : <span className="text-xs text-fg-faint">—</span>}</td>
                        <td className="text-right" onClick={(e) => e.stopPropagation()}>
                          <button className="btn-primary btn-sm" disabled={r.status !== "QUALIFIED" || r.validity !== "VALID" || (r.trade && ["PENDING_ENTRY", "OPEN", "CONFIGURED"].includes(r.trade.status))} onClick={() => setSelected(r)}>Enable Auto Trade</button>
                        </td>
                      </tr>
                      {expanded === r.id && (
                        <tr><td colSpan={24} className="!whitespace-normal bg-ink">
                          <div className="grid gap-4 p-2 md:grid-cols-2">
                            <div>
                              <div className="label mb-2">Rule evaluation</div>
                              <ul className="space-y-1.5 text-sm">{r.checks?.map((c: any) => (
                                <li key={c.rule + c.name} className="flex gap-2"><Pill tone={c.passed ? "good" : "bad"}>{c.rule}</Pill><span className="text-fg-muted"><span className="text-fg">{c.name}</span> — {c.detail}</span></li>
                              ))}</ul>
                            </div>
                            <div>
                              <div className="label mb-2">Score components ({r.score.toFixed(0)}/100)</div>
                              <ul className="space-y-1 text-sm">{Object.entries(r.components ?? {}).map(([k, v]: any) => (
                                <li key={k} className="flex justify-between gap-3"><span className="text-fg-muted">{k.replace(/_/g, " ")}</span><span className="num">{v.points}/{v.max}</span></li>
                              ))}</ul>
                              {r.rejection_reasons?.length > 0 && <div className="mt-3 space-y-1">{r.rejection_reasons.map((x: string) => <div key={x} className="text-xs text-down">· {x}</div>)}</div>}
                              <div className="mt-3 text-[11px] text-fg-faint">A high score is not a probability of profit. Mandatory failures override the score.</div>
                            </div>
                          </div>
                        </td></tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {selected && <AutoTradeModalD2 signal={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
