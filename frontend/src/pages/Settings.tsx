import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorBox, Field, Notice, Spinner, Toggle } from "../components/ui";
import { ago, money, time } from "../lib/format";

function Card({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-ink-line bg-ink-panel p-5">
      <div className="mb-4 flex items-center justify-between gap-3"><h2 className="font-semibold">{title}</h2>{right}</div>
      {children}
    </section>
  );
}

function StatusText({ status }: { status?: string }) {
  const ok = status === "CONNECTED";
  const label: Record<string, string> = { CONNECTED: "Connected", NOT_CONFIGURED: "Not set up", UNTESTED: "Saved — not tested", AUTH_FAILED: "Wrong or expired token", PERMISSION_DENIED: "Data API not enabled", NETWORK_ERROR: "Can't reach server", RATE_LIMITED: "Rate limited", MARKET_DATA_UNAVAILABLE: "No market data", QUOTA_EXCEEDED: "Quota exceeded" };
  return <span className={`text-sm ${ok ? "text-up" : status === "UNTESTED" || status === "NOT_CONFIGURED" ? "text-warn" : "text-down"}`}>● {label[status ?? ""] ?? status?.replace(/_/g, " ").toLowerCase()}</span>;
}

export default function Settings() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-fg-muted">Only Dhan is required. Everything else is automatic.</p>
      </div>
      <DhanCard />
      <StockListsCard />
      <AccountsCard />
      <OpenAICard />
      <div className="text-center text-xs text-fg-faint"><Link to="/system" className="underline">System details & logs</Link></div>
    </div>
  );
}

function DhanCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["dhan"], queryFn: () => api("/api/settings/dhan") });
  const [cid, setCid] = useState("");
  const [tok, setTok] = useState("");
  const [editing, setEditing] = useState(false);
  const inv = () => qc.invalidateQueries();
  const save = useMutation({
    mutationFn: async () => {
      const body: any = {};
      if (cid) { body.client_id = cid; body.confirm_replace_client_id = true; }
      if (tok) body.access_token = tok;
      await api("/api/settings/dhan", { method: "PUT", body });
      return api("/api/settings/dhan/test", { method: "POST" });
    },
    onSuccess: () => { inv(); setEditing(false); setTok(""); setCid(""); },
  });
  const test = useMutation({ mutationFn: () => api("/api/settings/dhan/test", { method: "POST" }), onSuccess: inv });
  const d = q.data;
  if (!d) return <Card title="Dhan account"><Spinner /></Card>;
  const showForm = editing || !d.client_id_set || !d.access_token_set;
  return (
    <Card title="Dhan account" right={<StatusText status={d.status} />}>
      {showForm ? (
        <div className="space-y-3">
          <Field label="Client ID"><input className="input num" value={cid} onChange={(e) => setCid(e.target.value.trim())} placeholder={d.client_id ?? "e.g. 1100000000"} /></Field>
          <Field label="Access token" hint="Dhan web → My Profile → Access DhanHQ APIs. Tokens usually last 24 hours.">
            <input className="input num" type="password" autoComplete="off" value={tok} onChange={(e) => setTok(e.target.value)} placeholder={d.access_token_set ? "Paste a new token" : "Paste token"} />
          </Field>
          <div className="flex gap-2">
            <button className="btn-primary" disabled={(!cid && !d.client_id_set) || (!tok && !d.access_token_set) || save.isPending}
              onClick={() => { if (d.client_id_set && cid && cid !== d.client_id && !window.confirm(`Replace Client ID ${d.client_id} with ${cid}?`)) return; save.mutate(); }}>
              {save.isPending ? "Saving & testing…" : "Save & connect"}
            </button>
            {d.client_id_set && d.access_token_set && <button className="btn-ghost" onClick={() => setEditing(false)}>Cancel</button>}
          </div>
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-y-1">
            <span className="text-fg-muted">Client ID</span><span className="num text-right">{d.client_id}</span>
            <span className="text-fg-muted">Token</span><span className="num text-right">{d.access_token_masked}</span>
            <span className="text-fg-muted">Token saved</span><span className="text-right">{ago(d.access_token_updated_at)}</span>
          </div>
          {d.token_reminder_due && <Notice tone="warn">Your token is more than 24 hours old and has probably expired. Paste a new one.</Notice>}
          {d.status !== "CONNECTED" && d.status_detail?.message && <Notice tone="bad">{d.status_detail.message}</Notice>}
          <div className="flex gap-2">
            <button className="btn-ghost btn-sm" onClick={() => setEditing(true)}>Update token / ID</button>
            <button className="btn-ghost btn-sm" disabled={test.isPending} onClick={() => test.mutate()}>{test.isPending ? "Testing…" : "Test connection"}</button>
          </div>
        </div>
      )}
      {(save.error || test.error) && <div className="mt-3"><ErrorBox error={save.error || test.error} /></div>}
      <p className="mt-4 text-xs text-fg-faint">Dhan is used only to read prices and charts. This app cannot place real orders.</p>
    </Card>
  );
}

function StockListsCard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["universe-status"], queryFn: () => api("/api/settings/universe/status"), refetchInterval: 5000 });
  const refresh = useMutation({ mutationFn: () => api("/api/settings/universe/refresh", { method: "POST" }), onSuccess: () => qc.invalidateQueries() });
  const d = q.data;
  const row = (label: string, count: number, last: any, err: string | null, extra?: string) => (
    <div className="flex items-center justify-between gap-3 py-2 text-sm">
      <span>{label}</span>
      <span className="text-right">
        {count > 0 ? <span className="text-up">{count}{extra}</span> : <span className="text-warn">not loaded</span>}
        <span className="ml-3 text-xs text-fg-faint">{last ? `updated ${ago(last.at)}` : ""}</span>
        {err && count === 0 && <div className="max-w-sm text-xs text-down">{err.slice(0, 160)}</div>}
      </span>
    </div>
  );
  return (
    <Card title="Stock lists" right={
      <button className="btn-ghost btn-sm" disabled={refresh.isPending || d?.refreshing} onClick={() => refresh.mutate()}>{d?.refreshing ? <Spinner label="Downloading…" /> : "Refresh stock lists"}</button>
    }>
      {!d ? <Spinner /> : (
        <div className="divide-y divide-ink-line">
          {row("Nifty 100 (MTF Stocks)", d.NIFTY100.count, d.NIFTY100.last_success, d.NIFTY100.last_error, d.NIFTY100.count ? ` stocks · ${d.NIFTY100.mapped} linked to Dhan` : "")}
          {row("Nifty 250 (Swing Scanner)", d.NIFTY250.count, d.NIFTY250.last_success, d.NIFTY250.last_error, d.NIFTY250.count ? ` stocks · ${d.NIFTY250.mapped} linked to Dhan` : "")}
          {row("Dhan instrument list", d.SCRIP_MASTER.rows, d.SCRIP_MASTER.last_success, d.SCRIP_MASTER.last_error, " NSE stocks")}
        </div>
      )}
      <p className="mt-3 text-xs text-fg-faint">Downloaded automatically from NSE and Dhan when the app starts, refreshed weekly, and retried every 30 minutes if a download fails. Nothing to upload.</p>
    </Card>
  );
}

function AccountsCard() {
  const q = useQuery({ queryKey: ["accounts"], queryFn: () => api("/api/paper/accounts") });
  return (
    <Card title="Paper money">
      <div className="space-y-4">{q.data?.accounts?.map((a: any) => <AccountRow key={a.code} a={a} />)}</div>
    </Card>
  );
}

const LIMITS: [string, string][] = [
  ["risk_pct_per_trade", "Risk per trade (% of cash)"],
  ["max_risk_per_trade", "Max loss per trade (₹)"],
  ["max_allocation_per_trade", "Max amount per trade (₹)"],
  ["max_open_positions", "Max trades at once"],
];

function AccountRow({ a }: { a: any }) {
  const qc = useQueryClient();
  const [cap, setCap] = useState(String(a.initial_capital));
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(LIMITS.map(([k]) => [k, String(a.limits[k])])));
  const reset = useMutation({ mutationFn: () => api(`/api/paper/accounts/${a.code}/reset`, { body: { confirm: "RESET", initial_capital: Number(cap) } }), onSuccess: () => qc.invalidateQueries() });
  const save = useMutation({ mutationFn: () => api(`/api/paper/accounts/${a.code}/limits`, { method: "PUT", body: Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, Number(v)])) }), onSuccess: () => qc.invalidateQueries() });
  return (
    <div className="rounded-lg border border-ink-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium">{a.code === "D1_MTF" ? "MTF account" : "Swing account"}</div>
        <div className="text-sm text-fg-muted">Value <span className="num text-fg">{money(a.equity, 0)}</span> · started with <span className="num">{money(a.initial_capital, 0)}</span></div>
      </div>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-fg-faint">Risk settings & reset</summary>
        <div className="mt-3 grid grid-cols-2 gap-3">
          {LIMITS.map(([k, label]) => <Field key={k} label={label}><input className="input num" value={vals[k]} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} /></Field>)}
        </div>
        <button className="btn-ghost btn-sm mt-3" onClick={() => save.mutate()} disabled={save.isPending}>Save risk settings</button>
        {save.isError && <div className="mt-2"><ErrorBox error={save.error} /></div>}
        <div className="mt-4 flex items-end gap-2">
          <Field label="Start again with (₹)"><input className="input num !w-40" value={cap} onChange={(e) => setCap(e.target.value)} /></Field>
          <button className="btn-danger btn-sm mb-0.5" disabled={reset.isPending} onClick={() => window.confirm("Reset this paper account? Waiting trades are cancelled and trade results start from zero.") && reset.mutate()}>Reset account</button>
        </div>
        {reset.isError && <div className="mt-2"><ErrorBox error={reset.error} /></div>}
      </details>
    </div>
  );
}

function OpenAICard() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["openai"], queryFn: () => api("/api/settings/openai") });
  const [key, setKey] = useState("");
  const inv = () => qc.invalidateQueries({ queryKey: ["openai"] });
  const save = useMutation({ mutationFn: (b: any) => api("/api/settings/openai", { method: "PUT", body: b }), onSuccess: () => { inv(); setKey(""); } });
  const test = useMutation({ mutationFn: () => api("/api/settings/openai/test", { method: "POST" }), onSuccess: inv });
  const d = q.data;
  if (!d) return null;
  return (
    <Card title="AI explanations (optional)" right={d.api_key_set ? <StatusText status={d.status} /> : undefined}>
      <div className="space-y-3">
        <p className="text-sm text-fg-muted">Adds an “Explain with AI” button to setups. AI never changes trades or numbers.</p>
        <Field label="OpenAI API key" hint={d.api_key_set ? `Saved: ${d.api_key_masked} · ${time(d.api_key_updated_at)}` : undefined}>
          <div className="flex gap-2">
            <input className="input num" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder={d.api_key_set ? "Paste a new key to replace" : "sk-…"} />
            <button className="btn-ghost" disabled={key.length < 10} onClick={() => save.mutate({ api_key: key })}>Save</button>
          </div>
        </Field>
        {d.api_key_set && (
          <div className="flex flex-wrap items-center gap-3">
            <select className="input !w-auto" value={d.model} onChange={(e) => save.mutate({ model: e.target.value })}>
              {Array.from(new Set([d.model, ...d.available_models])).map((m: string) => <option key={m} value={m}>{m}</option>)}
            </select>
            <Toggle checked={d.enabled} onChange={(v) => save.mutate({ enabled: v })} label="Enabled" />
            <button className="btn-ghost btn-sm" disabled={test.isPending} onClick={() => test.mutate()}>{test.isPending ? "Testing…" : "Test"}</button>
          </div>
        )}
        {d.status_detail?.message && d.status !== "CONNECTED" && <Notice tone="bad">{d.status_detail.message}</Notice>}
        {(save.error || test.error) && <ErrorBox error={save.error || test.error} />}
      </div>
    </Card>
  );
}
