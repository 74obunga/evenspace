import { API_BASE } from "./apiBase";

async function getCsrfToken(): Promise<string> {
  console.debug("[CSRF] Requesting token from", `${API_BASE}/auth/csrf`);

  const response = await fetch(`${API_BASE}/auth/csrf`, {
    credentials: "include",
    cache: "no-store",
  });

  console.debug("[CSRF] Response status:", response.status);
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Could not get CSRF token (${response.status})`);
  }
  const body = await response.json() as { csrf_token: string };
  if (typeof body.csrf_token !== "string" || body.csrf_token.trim().length === 0) {
    throw new Error("CSRF token is missing from the authenticated API response");
  }
  return body.csrf_token;
}

function csrfExempt(path: string): boolean {
  return path.startsWith("/public/") || [
    "/auth/login", "/auth/register", "/auth/invitations/accept",
    "/auth/password-reset/request", "/auth/password-reset/complete",
    "/auth/email-verification/request", "/auth/email-verification/complete",
  ].includes(path);
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && !csrfExempt(path)) {
    headers.set("X-CSRF-Token", await getCsrfToken());
  }

  console.debug("[API CSRF]", {
    path,
    method,
    tokenHeaderPresent: headers.has("X-CSRF-Token"),
    tokenHeaderNonEmpty: Boolean(headers.get("X-CSRF-Token")?.trim()),
  });

  const response = await fetch(`${API_BASE}${path}`, { ...init, method, headers, credentials: "include" });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}
