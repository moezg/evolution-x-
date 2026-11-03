/** Thin fetch wrapper. Same-origin by default; override with NEXT_PUBLIC_API_BASE for `next dev`. */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function parseError(res: Response): Promise<ApiError> {
  let detail = res.statusText || "request failed";
  try {
    const text = await res.text();
    try {
      const j = JSON.parse(text);
      if (j && typeof j.detail === "string") detail = j.detail;
      else if (j && j.detail) detail = JSON.stringify(j.detail);
      else if (text) detail = text.slice(0, 300);
    } catch {
      if (text) detail = text.slice(0, 300);
    }
  } catch {
    /* ignore */
  }
  return new ApiError(res.status, detail);
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), { signal, cache: "no-store" });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "backend unreachable");
  }
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

export async function apiText(path: string): Promise<string> {
  const res = await fetch(apiUrl(path), { cache: "no-store" });
  if (!res.ok) throw await parseError(res);
  return res.text();
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    throw new ApiError(0, "backend unreachable");
  }
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.status ? `${e.detail} (HTTP ${e.status})` : e.detail;
  if (e instanceof Error) return e.message;
  return String(e);
}
