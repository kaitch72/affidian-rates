// Keeps the last copy of the rates page and rates.json so the screen still
// works if the player starts up without internet. Always tries the network first.
const CACHE = "affidian-rates-v1";

self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  const sameSite = url.origin === self.location.origin;
  const font = url.hostname.endsWith("fonts.googleapis.com") || url.hostname.endsWith("fonts.gstatic.com");
  if (!sameSite && !font) return;

  // Store rates.json under one key no matter the ?v= cache-buster.
  const key = sameSite ? url.origin + url.pathname : e.request.url;

  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res && (res.ok || res.type === "opaque")) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(key, copy));
        }
        return res;
      })
      .catch(() => caches.match(key).then((hit) => hit || Response.error()))
  );
});
