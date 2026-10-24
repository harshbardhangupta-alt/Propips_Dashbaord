import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "../api/client";
import { ErrorBox, Field, KV, Notice, Panel, Pill, Spinner, Toggle } from "../components/ui";
import { ago, money, time } from "../lib/format";

export default function Settings() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Settings & API Credentials</h1>
        <p className="mt-1 text-sm text-fg-muted">Secrets are encrypted at rest in the local database and never returned in full to the browser. There is no live-trading setting.</p>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <DhanCard />
        <OpenAICard />
      </div>
      <UniverseCard />
      <AccountsCard />
      <CalendarCard />
    </div>
  );
}

function DhanCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["dhan"], queryFn: () => api("/api/settings/dhan") });
  const [editId, setEditId] = useState(false);
  const [cid, setCid] = useState("");
  const [replaceTok, setReplaceTok] = useState(false);
  const [tok, setTok] = useState("");
  const [confirmDel, setConfirmDel] = useState(false);
  const inv = () => { qc.invalidateQueries({ queryKey: ["dhan"] }); qc.invalidateQueries({ queryKey: ["system-status"] }); };
  const save = useMutation({ mutationFn: (b: any) => api("/api/settings/dhan", { method: "PUT", body: b }), onSuccess: () => { inv(); setEditId(false); setReplaceTok(false); setTok(""); } });
  const test = useMutation({ mutationFn: () => api("/api/settings/dhan/test", { method: "POST" }), onSuccess: inv });
  const del = useMutation({ mutationFn: () => api("/api/settings/dhan?confirm=true", { method: "DELETE" }), onSuccess: () => { inv(); setConfirmDel(false); } });
  const d = q.data;
  if (!d) return <Panel title="DhanHQ market data"><Spinner /></Panel>;
  const detail = d.status_detail ?? {};
  return (
    <Panel title="DhanHQ market data" actions={<Pill value={d.status} />}>
      <div className="space-y-5">
        <Notice tone="muted">Dhan is used ONLY for read-only market data (profile check, candles, quote snapshots). This app contains no order-placement code.</Notice>
        <Field label="Client ID" hint={d.client_id_set ? "Fixed until you explicitly edit it" : "Your Dhan client ID"}>
          {d.client_id_set && !editId ? (
            <div className="flex gap-2"><input className="input num" value={d.client_id} readOnly /><button className="btn-ghost btn-sm" onClick={() => { setEditId(true); setCid(d.client_id); }}><span className="whitespace-nowrap">Edit Client ID</span></button></div>
          ) : (
            <div className="flex gap-2">
              <input className="input num" value={cid} onChange={(e) => setCid(e.target.value.trim())} placeholder="e.g. 1100000000" />
              <button className="btn-primary btn-sm" disabled={!cid || save.isPending} onClick={() => {
                if (d.client_id_set && cid !== d.client_id && !window.confirm(`Replace saved Client ID ${d.client_id} with ${cid}?`)) return;
                save.mutate({ client_id: cid, confirm_replace_client_id: true });
              }}>Save</button>
              {d.client_id_set && <button className="btn-ghost btn-sm" onClick={() => setEditId(false)}>Cancel</button>}
            </div>
          )}
        </Field>
        <Field label="Access token" hint={d.access_token_set ? `Updated ${time(d.access_token_updated_at)} (${ago(d.access_token_updated_at)})` : "Generate in Dhan web → My Profile → Access DhanHQ APIs"}>
          {d.access_token_set && !replaceTok ? (
            <div className="flex gap-2"><input className="input num" value={d.access_token_masked} readOnly /><button className="btn-ghost btn-sm whitespace-nowrap" onClick={() => setReplaceTok(true)}>Update / Replace token</button></div>
          ) : (
            <div className="flex gap-2">
              <input className="input num" type="password" autoComplete="off" value={tok} onChange={(e) => setTok(e.target.value)} placeholder="Paste access token" />
              <button className="btn-primary btn-sm" disabled={tok.length < 10 || save.isPending} onClick={() => save.mutate({ access_token: tok })}>Save</button>
              {d.access_token_set && <button className="btn-ghost btn-sm" onClick={() => { setReplaceTok(false); setTok(""); }}>Cancel</button>}
            </div>
          )}
        </Field>
        {d.token_reminder_due && <Notice tone="warn">Your token was saved more than 24 hours ago and may have expired. {d.token_reminder_note}</Notice>}
        {!d.token_reminder_due && d.access_token_set && <div className="text-xs text-fg-faint">{d.token_reminder_note}</div>}
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn-ghost" disabled={!d.client_id_set || !d.access_token_set || test.isPending} onClick={() => test.mutate()}>{test.isPending ? <Spinner label="Testing…" /> : "Test Dhan Connection"}</button>
          {!confirmDel ? <button className="btn-danger btn-sm ml-auto" disabled={!d.client_id_set && !d.access_token_set} onClick={() => setConfirmDel(true)}>Delete credentials</button> : (
            <span className="ml-auto flex items-center gap-2 text-xs text-down">Delete Dhan credentials? <button className="btn-danger btn-sm" onClick={() => del.mutate()}>Delete</button><button className="btn-ghost btn-sm" onClick={() => setConfirmDel(false)}>Keep</button></span>
          )}
        </div>
        {(save.error || test.error || del.error) && <ErrorBox error={save.error || test.error || del.error} />}
        {detail.tested_at && (
          <div className="rounded-lg border border-ink-line bg-ink p-3 text-sm">
            <div className="mb-2 flex items-center gap-2"><Pill value={detail.status} /><span className="text-xs text-fg-faint">tested {time(detail.tested_at)}{detail.step ? ` · failed at ${detail.step}` : ""}</span></div>
            <div className="text-fg-muted">{detail.message}</div>
            {detail.profile && <div className="mt-2"><KV rows={Object.entries(detail.profile).map(([k, v]) => [k, String(v ?? "—")])} /></div>}
            {detail.market_data_probe && <div className="mt-2 text-xs text-fg-faint">Market-data probe: {detail.market_data_probe.symbol} LTP {String(detail.market_data_probe.ltp)}</div>}
          </div>
        )}
      </div>
    </Panel>
  );
}

function OpenAICard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["openai"], queryFn: () => api("/api/settings/openai") });
  const [key, setKey] = useState("");
  const [replace, setReplace] = useState(false);
  const inv = () => qc.invalidateQueries({ queryKey: ["openai"] });
  const save = useMutation({ mutationFn: (b: any) => api("/api/settings/openai", { method: "PUT", body: b }), onSuccess: () => { inv(); setKey(""); setReplace(false); } });
  const test = useMutation({ mutationFn: () => api("/api/settings/openai/test", { method: "POST" }), onSuccess: inv });
  const del = useMutation({ mutationFn: () => api("/api/settings/openai?confirm=true", { method: "DELETE" }), onSuccess: inv });
  const d = q.data;
  if (!d) return <Panel title="OpenAI explanations"><Spinner /></Panel>;
  const st = d.status_detail ?? {};
  return (
    <Panel title="OpenAI explanations (optional)" actions={<Pill value={d.status} />}>
      <div className="space-y-5">
        <Notice tone="muted">AI only explains results the deterministic engines already calculated. It cannot change signals, risk limits, allocations or paper trades, and the app works fully without it.</Notice>
        <Field label="API key" hint={d.api_key_set ? `Saved ${time(d.api_key_updated_at)} · fixed until replaced` : "Stored encrypted; never shown in full"}>
          {d.api_key_set && !replace ? (
            <div className="flex gap-2"><input className="input num" value={d.api_key_masked} readOnly /><button className="btn-ghost btn-sm whitespace-nowrap" onClick={() => setReplace(true)}>Update API key</button></div>
          ) : (
            <div className="flex gap-2">
              <input className="input num" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="sk-…" />
              <button className="btn-primary btn-sm" disabled={key.length < 10} onClick={() => save.mutate({ api_key: key })}>Save</button>
              {d.api_key_set && <button className="btn-ghost btn-sm" onClick={() => setReplace(false)}>Cancel</button>}
            </div>
          )}
        </Field>
        <Field label="Model" hint={`${d.models_source}. Current: ${d.model}`}>
          <select className="input" value={d.model} onChange={(e) => save.mutate({ model: e.target.value })}>
            {Array.from(new Set([d.model, ...d.available_models])).map((m: string) => <option key={m} value={m}>{m}</option>)}
          </select>
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <Toggle checked={d.enabled} onChange={(v) => save.mutate({ enabled: v })} label="Enable AI explanations" />
          <button className="btn-ghost btn-sm" disabled={!d.api_key_set || test.isPending} onClick={() => test.mutate()}>{test.isPending ? <Spinner label="Testing…" /> : "Test OpenAI Connection"}</button>
          {d.api_key_set && <button className="btn-danger btn-sm ml-auto" onClick={() => window.confirm("Delete the saved OpenAI API key?") && del.mutate()}>Delete key</button>}
        </div>
        {(save.error || test.error) && <ErrorBox error={save.error || test.error} />}
        {st.tested_at && (
          <div className="rounded-lg border border-ink-line bg-ink p-3 text-sm">
            <div className="flex items-center gap-2"><Pill value={st.status} /><span className="text-xs text-fg-faint">tested {time(st.tested_at)} · last success {time(st.last_success_at)}</span></div>
            <div className="mt-1 text-fg-muted">{st.message}</div>
          </div>
        )}
      </div>
    </Panel>
  );
}

function UploadButton({ label, url, onDone }: { label: string; url: string; onDone: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const m = useMutation({
    mutationFn: (f: File) => { const fd = new FormData(); fd.append("file", f); return api(url, { form: fd }); },
    onSuccess: onDone,
  });
  return (
    <span className="inline-flex flex-col">
      <input ref={ref} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => e.target.files?.[0] && m.mutate(e.target.files[0])} />
      <button className="btn-ghost btn-sm" disabled={m.isPending} onClick={() => ref.current?.click()}>{m.isPending ? <Spinner label="Uploading…" /> : label}</button>
      {m.isError && <span className="mt-1 text-xs text-down max-w-xs">{(m.error as Error).message}</span>}
      {m.isSuccess && <span className="mt-1 text-xs text-up">Imported</span>}
    </span>
  );
}

function UniverseCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["universe"], queryFn: () => api("/api/settings/universe") });
  const inv = () => qc.invalidateQueries();
  const sync = useMutation({ mutationFn: (path: string) => api(path, { method: "POST" }), onSuccess: inv });
  const d = q.data;
  return (
    <Panel title="Universes & instrument mapping">
      {!d ? <Spinner /> : (
        <div className="space-y-5">
          <div className="text-sm text-fg-muted">
            Order of operations: <b className="text-fg">1.</b> Dhan scrip master (instrument ids) → <b className="text-fg">2.</b> Nifty 100 → <b className="text-fg">3.</b> Nifty 250. Download uses the official public files; if your network blocks them, download the CSV yourself and upload it. Constituents are never invented.
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="rounded-xl border border-ink-line bg-ink p-4 space-y-3">
              <div className="flex items-center justify-between"><div className="font-medium">Dhan scrip master</div><span className="num text-xs text-fg-faint">{d.SCRIP_MASTER.cached_rows} NSE EQ rows</span></div>
              <div className="text-xs text-fg-faint">Last success: {d.SCRIP_MASTER.last_success ? `${time(d.SCRIP_MASTER.last_success.at)} · ${d.SCRIP_MASTER.last_success.source}` : "never"}</div>
              <div className="flex flex-wrap gap-2">
                <button className="btn-ghost btn-sm" disabled={sync.isPending} onClick={() => sync.mutate("/api/settings/scrip-master/sync")}>Download from Dhan</button>
                <UploadButton label="Upload CSV" url="/api/settings/scrip-master/upload" onDone={inv} />
              </div>
              <div className="text-[11px] text-fg-faint break-all">images.dhan.co/api-data/api-scrip-master.csv</div>
            </div>
            {(["NIFTY100", "NIFTY250"] as const).map((u) => (
              <div key={u} className="rounded-xl border border-ink-line bg-ink p-4 space-y-3">
                <div className="flex items-center justify-between"><div className="font-medium">{d[u].label}</div><span className="num text-xs text-fg-faint">{d[u].mapped}/{d[u].count} mapped</span></div>
                <div className="text-xs text-fg-faint">Last success: {d[u].last_success ? `${time(d[u].last_success.at)} · ${d[u].last_success.status}` : "never"}</div>
                <div className="flex flex-wrap gap-2">
                  <button className="btn-ghost btn-sm" disabled={sync.isPending} onClick={() => sync.mutate(`/api/settings/universe/${u}/sync`)}>Download official list</button>
                  <UploadButton label="Upload CSV" url={`/api/settings/universe/${u}/upload`} onDone={inv} />
                </div>
                <div className="text-[11px] text-fg-faint break-all">{d.sources[u][0]}</div>
                {d[u].issues.length > 0 && (
                  <details className="text-xs"><summary className="cursor-pointer text-warn">{d[u].issues.length} mapping issue(s)</summary>
                    <ul className="mt-2 space-y-1 max-h-40 overflow-auto">{d[u].issues.map((i: any) => <li key={i.symbol}><span className="text-fg">{i.symbol}</span> <Pill value={i.status} /> <span className="text-fg-faint">{i.note}</span></li>)}</ul>
                  </details>
                )}
              </div>
            ))}
          </div>
          {sync.isError && <ErrorBox error={sync.error} />}
          {sync.isPending && <Spinner label="Syncing…" />}
          <div>
            <div className="label mb-2">Refresh history</div>
            <div className="table-wrap max-h-56"><table className="data"><thead><tr><th>Time</th><th>Universe</th><th>Status</th><th className="text-right">Count</th><th>Message</th></tr></thead>
              <tbody>{d.history.map((h: any) => <tr key={h.id}><td className="text-xs">{time(h.created_at)}</td><td>{h.universe}</td><td><Pill value={h.status} /></td><td className="num text-right">{h.count}</td><td className="!whitespace-normal text-xs text-fg-muted">{h.message}</td></tr>)}</tbody></table></div>
          </div>
        </div>
      )}
    </Panel>
  );
}

const LIMIT_FIELDS: [string, string, string][] = [
  ["risk_pct_per_trade", "Risk % per trade", "% of available paper cash"],
  ["max_risk_per_trade", "Max risk per trade (₹)", ""],
  ["max_allocation_per_trade", "Max allocation per trade (₹)", ""],
  ["max_open_positions", "Max simultaneous positions", "open + pending"],
  ["max_aggregate_risk_pct", "Max aggregate planned risk %", "of initial capital"],
  ["min_reward_risk", "Minimum reward:risk", "D1 ≥ 1, D2 ≥ 3 (strategy floor)"],
  ["slippage_bps", "Simulated slippage (bps)", ""],
  ["max_entry_deviation_pct", "Max entry deviation %", "fills beyond this are not chased"],
];

function AccountsCard() {
  const q = useQuery({ queryKey: ["accounts"], queryFn: () => api("/api/paper/accounts") });
  return (
    <Panel title="Paper accounts & risk limits">
      <div className="grid gap-4 lg:grid-cols-2">{q.data?.accounts?.map((a: any) => <AccountEditor key={a.code} a={a} />)}</div>
    </Panel>
  );
}

function AccountEditor({ a }: { a: any }) {
  const qc = useQueryClient();
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(LIMIT_FIELDS.map(([k]) => [k, String(a.limits[k])])));
  const [resetText, setResetText] = useState("");
  const [cap, setCap] = useState(String(a.initial_capital));
  const save = useMutation({ mutationFn: () => api(`/api/paper/accounts/${a.code}/limits`, { method: "PUT", body: Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, Number(v)])) }), onSuccess: () => qc.invalidateQueries() });
  const reset = useMutation({ mutationFn: () => api(`/api/paper/accounts/${a.code}/reset`, { body: { confirm: resetText, initial_capital: Number(cap) } }), onSuccess: () => { qc.invalidateQueries(); setResetText(""); } });
  return (
    <div className="rounded-xl border border-ink-line bg-ink p-4 space-y-4">
      <div className="flex items-center justify-between"><div className="font-medium">{a.name}</div><span className="text-xs text-fg-faint">initial {money(a.initial_capital, 0)} · equity {money(a.equity, 0)}</span></div>
      <div className="grid grid-cols-2 gap-3">
        {LIMIT_FIELDS.map(([k, label, hint]) => (
          <Field key={k} label={label} hint={hint}><input className="input num" value={vals[k]} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} /></Field>
        ))}
      </div>
      <div className="flex justify-end"><button className="btn-ghost btn-sm" onClick={() => save.mutate()} disabled={save.isPending}>Save limits</button></div>
      {save.isError && <ErrorBox error={save.error} />}
      {save.isSuccess && <div className="text-xs text-up">Saved</div>}
      <div className="border-t border-ink-line pt-4 space-y-2">
        <div className="label">Reset paper account</div>
        <div className="text-xs text-fg-faint">Cancels pending entries and restores cash to the initial capital. Requires no open positions. Type RESET to confirm.</div>
        <div className="flex gap-2">
          <input className="input num !w-36" value={cap} onChange={(e) => setCap(e.target.value)} />
          <input className="input !w-32" placeholder="RESET" value={resetText} onChange={(e) => setResetText(e.target.value)} />
          <button className="btn-danger btn-sm" disabled={resetText !== "RESET" || reset.isPending} onClick={() => reset.mutate()}>Reset</button>
        </div>
        {reset.isError && <ErrorBox error={reset.error} />}
      </div>
    </div>
  );
}

function CalendarCard() {
  const q = useQuery({ queryKey: ["calendar"], queryFn: () => api("/api/settings/calendar") });
  const d = q.data;
  return (
    <Panel title="NSE trading calendar">
      {!d ? <Spinner /> : (
        <div className="space-y-3">
          <div className="text-sm text-fg-muted">Today {d.today}: {d.is_trading_day ? "trading day" : `closed (${d.holiday_name})`} · next trading day {d.next_trading_day}. Holidays are maintained in <code className="text-fg">{d.file}</code>.</div>
          {!d.year_status.verified && <Notice tone="warn">The {d.year_status.year} holiday list is {d.year_status.present ? "marked UNVERIFIED" : "missing"}. Check it against the official NSE circular and set "verified": true. {d.year_status.source}</Notice>}
          <div className="flex flex-wrap gap-2">{d.holidays.map((h: any) => <span key={h.date} className="chip border-ink-line text-fg-muted"><span className="num">{h.date}</span> {h.name}</span>)}</div>
        </div>
      )}
    </Panel>
  );
}
