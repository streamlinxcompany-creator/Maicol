/* Service worker de JARVIS: hace que se pueda instalar como app.
   Siempre pide la versión nueva a la red; solo si no hay conexión muestra la copia guardada
   (o un aviso), así nunca te quedas con una interfaz vieja. La conversación (WebSocket y /api) no se guarda. */
const CACHE = "jarvis-v5";
const BASICOS = ["/", "/static/estilo.css", "/static/app.js", "/static/icono-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(BASICOS)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/") || url.pathname === "/ws") return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        if (r.ok) { const copia = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copia)); }
        return r;
      })
      .catch(() => caches.match(e.request).then((r) => r || new Response(
        "<body style='background:#04090f;color:#00e5ff;font-family:sans-serif;display:grid;place-items:center;height:100vh;text-align:center'>" +
        "<div><h2>M.A.I.C.O.L.</h2><p>Sin conexión con el cerebro.<br>¿Está encendido Tailscale?</p></div></body>",
        { headers: { "Content-Type": "text/html; charset=utf-8" } })))
  );
});
