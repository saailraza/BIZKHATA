/* BIZKHATA service worker: makes the web app installable and opens the screen fast.
   Account data is NEVER cached: every /api request always goes to the server. */
const V = 'bizkhata-v1';
const SHELL = ['/', '/offline.html', '/manifest.webmanifest', '/assets/logo.png', '/assets/favicon.png', '/assets/icon-192.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request, u = new URL(req.url);
  if (req.method !== 'GET' || u.origin !== location.origin || u.pathname.startsWith('/api/')) return;
  if (req.mode === 'navigate') {                                   // pages: online first, saved copy when offline
    e.respondWith(fetch(req).then(r => { const cp = r.clone(); caches.open(V).then(c => c.put('/', cp)); return r; })
      .catch(() => caches.match('/').then(r => r || caches.match('/offline.html'))));
    return;
  }
  if (u.pathname.startsWith('/assets/')) {                         // images: saved copy first
    e.respondWith(caches.match(req).then(r => r || fetch(req).then(x => { const cp = x.clone(); caches.open(V).then(c => c.put(req, cp)); return x; })));
  }
});
