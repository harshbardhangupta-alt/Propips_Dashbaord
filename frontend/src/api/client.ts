/** Thin fetch wrapper. All authority (cash, sizing, fills, risk) lives in the backend. */
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : errorText(detail));
    this.status = status;
    this.detail = detail;
  }
}

function errorText(d: unknown): string {
  if (!d) return "Request failed";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x && typeof x === "object" && "msg" in x ? `${(x as { loc?: string[] }).loc?.slice(-1)[0] ?? ""}: ${(x as { msg: string }).msg}` : String(x))).join("; ");
  if (typeof d === "object") {
    const o = d as Record<string, unknown>;
    if (Array.isArray(o.errors)) return (o.errors as string[]).join("; ");
    if (o.detail) return errorText(o.detail);
    if (o.message) return String(o.message);
  }
  return JSON.stringify(d);
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const init: RequestInit = { method: opts.method ?? (opts.body || opts.form ? "POST" : "GET"), headers: {} };
  if (opts.form) init.body = opts.form;
  else if (opts.body !== undefined) {
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new ApiError(0, "Backend unreachable — is the API server running on 127.0.0.1:8000?");
  }
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
  return data as T;
}
