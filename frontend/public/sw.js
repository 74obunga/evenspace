const CACHE = "evenspace-scanner-shell-v1";
const SHELL = ["/", "/manifest.webmanifest", "/evenspace-icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL);
    const manifestResponse = await fetch("/.vite/manifest.json");
    if (manifestResponse.ok) {
      const manifest = await manifestResponse.json();
      const assets = new Set();
      for (const entry of Object.values(manifest)) {
        if (entry.file) assets.add(`/${entry.file}`);
        for (const file of [...(entry.css ?? []), ...(entry.assets ?? [])]) assets.add(`/${file}`);
      }
      await cache.addAll([...assets]);
    }
  })());
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        const appResource = request.mode === "navigate" || url.pathname.startsWith("/assets/") || url.pathname.startsWith("/src/") || url.pathname.startsWith("/node_modules/.vite/") || url.pathname.endsWith(".webmanifest");
        const devRuntime = url.pathname.startsWith("/@vite/") || url.pathname.startsWith("/@react-refresh");
        if (response.ok && appResource && !devRuntime) {
          const copy = response.clone();
          void caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(async () => (await caches.match(request)) ?? (await caches.match("/"))),
  );
});
