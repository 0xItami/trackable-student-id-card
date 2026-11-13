const SHELL_CACHE = 'siid-shell-v3';
const MAP_CACHE = 'siid-map-v2';
const SHELL = [
  '/static/abu.css',
  '/static/app.js',
  '/static/abu-logo.jpg',
  '/static/crest-fallback.svg',
  '/static/offline-campus-map.svg',
  '/static/leaflet/leaflet.css',
  '/static/leaflet/leaflet.js',
  '/static/leaflet/images/marker-icon.png',
  '/static/leaflet/images/marker-icon-2x.png',
  '/static/leaflet/images/marker-shadow.png',
  '/static/socket.io.min.js'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL_CACHE).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(key => ![SHELL_CACHE, MAP_CACHE].includes(key)).map(key => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  // Location/API responses are deliberately never cached automatically.
  // The tracking page stores a clearly labelled snapshot only when requested.
  if (url.origin === location.origin && url.pathname.startsWith('/api/')) return;

  const isMapTile = request.destination === 'image' && (
    url.hostname.includes('openstreetmap.org') || url.hostname.includes('arcgisonline.com')
  );
  if (isMapTile) {
    event.respondWith(
      caches.open(MAP_CACHE).then(cache =>
        cache.match(request).then(saved => saved || fetch(request).then(response => {
          if (response.ok || response.type === 'opaque') cache.put(request, response.clone());
          return response;
        }))
      )
    );
    return;
  }

  if (url.origin === location.origin && url.pathname.startsWith('/static/')) {
    event.respondWith(caches.match(request).then(saved => saved || fetch(request)));
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).then(response => {
        if (response.ok) caches.open(SHELL_CACHE).then(cache => cache.put(request, response.clone()));
        return response;
      }).catch(() => caches.match(request).then(saved => saved || caches.match('/login')))
    );
  }
});
