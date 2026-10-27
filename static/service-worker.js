/* ============================================================
   S.I.P.A. · Service Worker v1.9
   - Cache-first para assets estáticos (CSS, JS, imágenes)
   - Network-first para HTML y endpoints API
   - Funciona offline una vez visitada la app al menos 1 vez
   - v1.7 → bump dark (Monitor KPIs, Auditoría, Pendientes, F.E.)
   - v1.8 → fix admin.js (cierre de string) + CSP Chart.js + migraciones DB
   - v1.9 → inventario de tablas completo (17 + 2): Telegram/Bot + versiones
   - v2.0 → Consola SQL: botones dinámicos para ver TODAS las tablas
   - v2.1 → fix CSS: input date readonly se comía el panel de Bedelía
   - v2.2 → Chart.js self-hosted (offline) + fix impersonación tapada por welcome
   - v3.0 → Bcrypt, dashboard histórico, PDF, offline queue, logs JSON, TG health
   ============================================================ */

const VERSION   = 'sipa-v6.6';
const CACHE_STATIC = `${VERSION}-static`;
const CACHE_DYN    = `${VERSION}-dynamic`;

// Recursos que se precachean en la instalación
const PRECACHE = [
    '/',
    '/static/css/estilos.css',
    '/static/js/main.js',
    '/static/js/bedelia.js',
    '/static/js/docente.js',
    '/static/js/admin.js',
    '/static/js/chart.umd.min.js',
    '/static/img/logo-tic.png',
    '/static/img/logo-escuela.png',
    '/static/img/foto-entrada.jpg',
    '/static/img/emblema-sables.png',
    '/manifest.json',
];

// ── INSTALACIÓN ──────────────────────────────────────────────
self.addEventListener('install', evt => {
    evt.waitUntil(
        caches.open(CACHE_STATIC)
            .then(cache => cache.addAll(PRECACHE).catch(() => {}))
            .then(() => self.skipWaiting())
    );
});

// ── ACTIVACIÓN: limpiar caches viejos ────────────────────────
self.addEventListener('activate', evt => {
    evt.waitUntil(
        caches.keys().then(keys => Promise.all(
            keys.filter(k => k !== CACHE_STATIC && k !== CACHE_DYN)
                .map(k => caches.delete(k))
        )).then(() => self.clients.claim())
    );
});

// ── FETCH: estrategia híbrida ───────────────────────────────
self.addEventListener('fetch', evt => {
    const req = evt.request;
    if (req.method !== 'GET') return;
    const url = new URL(req.url);

    // EXCLUSIÓN: streams SSE no se cachean (long-lived, romperían el cache)
    if (url.pathname.startsWith('/api/sse/')) {
        return; // dejar pasar sin interceptar
    }
    // 1. APIs (/api/*) → network-first con fallback a cache
    if (url.pathname.startsWith('/api/')) {
        // Nunca persistir respuestas administrativas o de sesiones. La caché
        // se comparte por URL y no distingue tokens de autenticación.
        const autenticada = req.headers.has('X-SU-Token') ||
                            req.headers.has('X-Admin-Token') ||
                            req.headers.has('X-Docente-Token') ||
                            req.headers.has('Authorization');
        if (autenticada) {
            evt.respondWith(fetch(req));
            return;
        }
        evt.respondWith(
            fetch(req)
                .then(resp => {
                    // Cachear respuestas OK por si después no hay red
                    const cacheControl = resp.headers.get('Cache-Control') || '';
                    if (resp.ok && !/no-store|private/i.test(cacheControl)) {
                        const copy = resp.clone();
                        caches.open(CACHE_DYN).then(c => c.put(req, copy));
                    }
                    return resp;
                })
                .catch(() => caches.match(req).then(c => c || new Response(
                    JSON.stringify({ error: 'Sin conexión y sin datos cacheados', offline: true }),
                    { status: 503, headers: { 'Content-Type': 'application/json' } }
                )))
        );
        return;
    }

    // 2. Navegación HTML → network-first con fallback al HTML cacheado
    if (req.mode === 'navigate' || req.headers.get('accept')?.includes('text/html')) {
        evt.respondWith(
            fetch(req)
                .then(resp => {
                    const copy = resp.clone();
                    caches.open(CACHE_DYN).then(c => c.put(req, copy));
                    return resp;
                })
                .catch(() => caches.match(req).then(c => c || caches.match('/')))
        );
        return;
    }

    // 3. Estáticos (CSS, JS, imágenes) → cache-first
    evt.respondWith(
        caches.match(req).then(cached => {
            if (cached) return cached;
            return fetch(req).then(resp => {
                if (resp.ok) {
                    const copy = resp.clone();
                    caches.open(CACHE_STATIC).then(c => c.put(req, copy));
                }
                return resp;
            }).catch(() => cached);
        })
    );
});

// ── Comando manual para limpiar caches (desde la app) ────────
self.addEventListener('message', evt => {
    if (evt.data === 'CLEAR_CACHE') {
        caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k))));
    }
    if (evt.data === 'FLUSH_OFFLINE_QUEUE') {
        _flushOfflineQueue().then(r => {
            if (evt.ports && evt.ports[0]) evt.ports[0].postMessage(r);
        });
    }
    if (evt.data && evt.data.type === 'ENQUEUE_OFFLINE') {
        _enqueueOffline(evt.data.url, evt.data.options || {});
    }
});


// ═══════════════════════════════════════════════════════════════
// COLA OFFLINE — Firmas que no pudieron enviarse se reintentan
// ═══════════════════════════════════════════════════════════════
const OFFLINE_STORE = 'sipa-offline-queue';

function _openOfflineDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(OFFLINE_STORE, 1);
        req.onupgradeneeded = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains('queue')) {
                db.createObjectStore('queue', { keyPath: 'id', autoIncrement: true });
            }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror   = () => reject(req.error);
    });
}

async function _enqueueOffline(url, options) {
    try {
        const db = await _openOfflineDB();
        const tx = db.transaction('queue', 'readwrite');
        tx.objectStore('queue').add({
            url, method: options.method || 'POST',
            headers: Object.fromEntries(new Headers(options.headers || {}).entries()),
            body: options.body || null,
            timestamp: Date.now()
        });
        await new Promise((res, rej) => { tx.oncomplete = res; tx.onerror = rej; });
        db.close();
    } catch (e) {
        console.error('[SW] Error encolando offline:', e);
    }
}

async function _flushOfflineQueue() {
    let enviados = 0, fallidos = 0;
    try {
        const db = await _openOfflineDB();
        const tx = db.transaction('queue', 'readonly');
        const items = await new Promise((res, rej) => {
            const req = tx.objectStore('queue').getAll();
            req.onsuccess = () => res(req.result);
            req.onerror   = () => rej(req.error);
        });
        db.close();

        for (const item of items) {
            try {
                const resp = await fetch(item.url, {
                    method: item.method,
                    headers: item.headers,
                    body: item.body
                });
                if (resp.ok || resp.status === 409) {
                    // Éxito o duplicado — eliminar de la cola
                    const db2 = await _openOfflineDB();
                    const tx2 = db2.transaction('queue', 'readwrite');
                    tx2.objectStore('queue').delete(item.id);
                    await new Promise(r => { tx2.oncomplete = r; });
                    db2.close();
                    enviados++;
                } else {
                    fallidos++;
                }
            } catch {
                fallidos++;  // Sigue sin red
            }
        }
    } catch (e) {
        console.error('[SW] Error procesando cola offline:', e);
    }
    return { enviados, fallidos };
}

// Intentar flush automático cuando vuelve la conexión
self.addEventListener('online', () => {
    _flushOfflineQueue();
});
