const LOCAL_API_BASE = "http://localhost:8000/api/v1";
const DEPLOYED_API_BASE = "https://evenspace-api.onrender.com/api/v1";

function localLoopback(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

function resolveApiBase(): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  if (typeof window === "undefined") return (configured || LOCAL_API_BASE).replace(/\/$/, "");

  try {
    const pageHost = window.location.hostname;
    const fallback = localLoopback(pageHost) ? LOCAL_API_BASE : DEPLOYED_API_BASE;
    const apiUrl = new URL(configured || fallback, window.location.origin);
    // A localhost API URL only works when the app itself is running locally.
    // This also protects production builds that accidentally used the Docker default.
    if (!localLoopback(pageHost) && localLoopback(apiUrl.hostname)) {
      return DEPLOYED_API_BASE;
    }
    // Keep local development cookies first-party across the two loopback aliases.
    if (localLoopback(pageHost) && localLoopback(apiUrl.hostname)) apiUrl.hostname = pageHost;
    return `${apiUrl.origin}${apiUrl.pathname}`.replace(/\/$/, "");
  } catch {
    return configured.replace(/\/$/, "");
  }
}

export const API_BASE = resolveApiBase();
