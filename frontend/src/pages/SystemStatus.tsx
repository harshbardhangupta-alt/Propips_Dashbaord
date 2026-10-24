import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorBox, KV, Notice, Panel, Pill, Spinner } from "../components/ui";
import { time } from "../lib/format";

export default function SystemStatus() {
  const q = useQuery({ queryKey: ["system-status"], queryFn: () => api("/api/system/status"), refetchInterval: 10000 });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api("/api/system/audit?limit=150"), refetchInterval: 15000 });
  const s = q.data;
  if (q.isLoading) return <Spinner label="Loading status…" />;
  if (q.isError) return <ErrorBox error={q.error} />;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">System Status</h1>
        <p className="mt-1 text-sm text-fg-muted">Live state of background workers, data connections and safety guarantees. Monitoring happens only while the backend runs.</p>
      </div>
      <div className="grid gap-5 lg:grid-cols-3">
        <Panel title="Execution safety">
          <KV rows={[
            ["Mode", <Pill tone="neon">{s.banner}</Pill>],
            ["Paper trading only", String(s.paper_trading_only)],
            ["Live trading available", String(s.live_trading_available)],
          ]} />
          <div className="mt-4 label">Only Dhan endpoints this app can call</div>
          <ul className="mt-2 space-y-1 text-xs num text-fg-muted">{s.allowed_dhan_endpoints.map((e: string) => <li key={e}>{e}</li>)}</ul>
          <div className="mt-3 text-[11px] text-fg-faint">Any other path (including every order endpoint) is refused in code before a request is sent.</div>
        </Panel>
        <Panel title="Connections & data">
          <KV rows={[
            ["Dhan", <Pill value={s.dhan.status} />],
            ["Dhan last test", time(s.dhan.detail?.tested_at)],
            ["OpenAI", <Pill value={s.openai.status} />],
            ["AI explanations", s.openai.enabled ? `enabled · ${s.openai.model}` : "disabled"],
            ["Newest quote", time(s.market_data.newest_quote_at)],
            ["Quote state", <Pill value={s.market_data.state} />],
          ]} />
          <div className="mt-3 text-[11px] text-fg-faint">{s.market_data.quote_mode}</div>
        </Panel>
        <Panel title="Market & storage">
          <KV rows={[
            ["IST now", time(s.now_ist)],
            ["Trading day", s.trading_day ? "yes" : `no (${s.holiday})`],
            ["Market open", s.market_open ? "yes" : "no"],
            ["Holiday calendar", s.calendar.verified ? "verified" : s.calendar.present ? "UNVERIFIED" : "missing"],
            ["MTF snapshots", s.counts.mtf_snapshots],
            ["Stored signals", s.counts.signals],
            ["Database", <span className="text-xs break-all">{s.database}</span>],
          ]} />
          {!s.calendar.verified && <div className="mt-3"><Notice tone="warn">Holiday list for {s.calendar.year} is not verified — see Settings.</Notice></div>}
        </Panel>
      </div>
      <Panel pad={false} title={<span className="flex items-center gap-2">Background jobs <Pill value={s.scheduler.running ? "RUNNING" : "DISABLED"}>{s.scheduler.running ? "SCHEDULER RUNNING" : "SCHEDULER STOPPED"}</Pill></span>}>
        <div className="table-wrap !rounded-none !border-0">
          <table className="data">
            <thead><tr><th>Job</th><th>Description</th><th>Next run</th><th>Last run</th><th>Last status</th><th>Runs</th><th>Last message</th></tr></thead>
            <tbody>{s.scheduler.jobs.map((j: any) => (
              <tr key={j.id}><td className="num text-xs">{j.id}</td><td className="text-fg-muted">{j.description}</td><td className="text-xs">{time(j.next_run)}</td><td className="text-xs">{time(j.last_run_at)}</td><td>{j.last_status ? <Pill value={j.last_status} /> : "—"}</td><td className="num">{j.run_count}</td><td className="!whitespace-normal text-xs text-fg-muted max-w-md">{j.last_message ?? "—"}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Dashboard 2 scanner">
        <KV rows={[
          ["Running", s.scanner.running ? `yes · ${s.scanner.progress.done}/${s.scanner.progress.total} (${s.scanner.progress.current ?? ""})` : "no"],
          ["Latest scan", s.scanner.latest ? `#${s.scanner.latest.id} ${s.scanner.latest.kind} · ${s.scanner.latest.status} · ${time(s.scanner.latest.finished_at ?? s.scanner.latest.started_at)}` : "none"],
          ["Latest message", <span className="text-xs whitespace-normal">{s.scanner.latest?.message ?? "—"}</span>],
        ]} />
      </Panel>
      <Panel pad={false} title="Audit & error log">
        {audit.isLoading ? <div className="p-5"><Spinner /></div> : (
          <div className="table-wrap !rounded-none !border-0 max-h-[50vh]">
            <table className="data"><thead><tr><th>Time</th><th>Level</th><th>Source</th><th>Message</th></tr></thead>
              <tbody>{audit.data?.map((e: any) => (
                <tr key={e.id}><td className="text-xs">{time(e.at)}</td><td><Pill tone={e.level === "ERROR" ? "bad" : e.level === "WARN" ? "warn" : "muted"}>{e.level}</Pill></td><td className="text-xs text-fg-muted">{e.source}</td><td className="!whitespace-normal text-sm text-fg-muted">{e.message}</td></tr>
              ))}</tbody></table>
          </div>
        )}
      </Panel>
    </div>
  );
}
