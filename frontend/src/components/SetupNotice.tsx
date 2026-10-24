import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Notice, Spinner } from "./ui";

/** Explains why a list is empty: stock lists are fetched automatically, Dhan needs credentials. */
export function SetupNotice({ universe }: { universe: "NIFTY100" | "NIFTY250" }) {
  const u = useQuery({ queryKey: ["universe-status"], queryFn: () => api("/api/settings/universe/status"), refetchInterval: 5000 });
  const d = u.data;
  if (!d) return <Spinner />;
  const x = d[universe];
  if (d.refreshing && x.count === 0) return <Spinner label="Downloading the stock list from NSE…" />;
  if (x.count === 0)
    return (
      <Notice tone="warn">
        The stock list hasn't been downloaded yet. It is fetched automatically from NSE and retried every 30 minutes.
        {x.last_error && <div className="mt-1 text-xs opacity-80">Last attempt failed: {x.last_error}</div>}
        <div className="mt-1 text-xs">Check your internet connection, or press “Refresh stock lists” in <Link to="/settings" className="underline">Settings</Link>.</div>
      </Notice>
    );
  if (x.mapped === 0)
    return <Notice tone="warn">Stocks loaded, but Dhan instrument ids aren't yet. {d.SCRIP_MASTER.last_error ?? "Downloading automatically…"}</Notice>;
  return null;
}
