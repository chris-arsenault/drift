const API = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body != null ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}
