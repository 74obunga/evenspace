const DEFAULT_API_BASE = "http://localhost:8000/api/v1";

function localLoopback(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

function resolveApiBase(): string {
  const configured = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE;
  if (typeof window === "undefined") return configured.replace(/\/$/, "");

  try {
    const apiUrl = new URL(configured, window.location.origin);
    const pageHost = window.location.hostname;
    // Keep local development cookies first-party across the two loopback aliases.
    if (localLoopback(pageHost) && localLoopback(apiUrl.hostname)) apiUrl.hostname = pageHost;
    return `${apiUrl.origin}${apiUrl.pathname}`.replace(/\/$/, "");
  } catch {
    return configured.replace(/\/$/, "");
  }
}

export const API_BASE = resolveApiBase();
