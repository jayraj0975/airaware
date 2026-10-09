// AirAware service worker: the app opens offline and shows the last forecast it saw.
// - /assets/* (hashed, never change): cache first.
// - pages: network first, falling back to the cached app shell.
// - public API reads (forecasts, stations, insights): network first, falling back to the last copy.
// - anything personal (/api/me, /api/auth, /api/admin, and any response the server marks X-AirAware-Personal because
//   it was tailored to the signed-in user's health profile) and every write: never cached.
// - signing out (a message from the page) empties the cache.
const VERSION = 'airaware-v2'
const PUBLIC_API = ['/api/status', '/api/overview', '/api/stations', '/api/insights', '/api/model', '/api/reports', '/api/track-record']

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(['/', '/manifest.webmanifest', '/icon-192.png'])))
  self.skipWaiting()
})

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))))
  self.clients.claim()
})

async function networkFirst(request, fallbackUrl) {
  const cache = await caches.open(VERSION)
  try {
    const response = await fetch(request)
    if (response.ok && !response.headers.has('X-AirAware-Personal')) cache.put(request, response.clone())
    return response
  } catch (err) {
    const hit = (await cache.match(request)) || (fallbackUrl && (await cache.match(fallbackUrl)))
    if (hit) return hit
    throw err
  }
}

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  if (e.request.method !== 'GET' || url.origin !== location.origin) return
  if (url.pathname.startsWith('/assets/')) {
    e.respondWith(caches.open(VERSION).then(async (c) => (await c.match(e.request)) || fetch(e.request).then((r) => { if (r.ok) c.put(e.request, r.clone()); return r })))
  } else if (PUBLIC_API.some((p) => url.pathname === p)) {
    e.respondWith(networkFirst(e.request))
  } else if (e.request.mode === 'navigate') {
    e.respondWith(networkFirst(e.request, '/'))
  }
})

self.addEventListener('message', (e) => {
  if (e.data === 'signed-out') e.waitUntil(caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k)))))
})
