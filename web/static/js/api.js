const BASE = '';

const REQUEST_TIMEOUT = 120000;

async function request(method, path, body = null, options = {}) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);

  const timeout = options.timeout === undefined ? REQUEST_TIMEOUT : options.timeout;
  let ctrl = null, to = null;
  if (options.signal) {
    opts.signal = options.signal;
  } else if (timeout > 0) {
    ctrl = new AbortController();
    opts.signal = ctrl.signal;
    to = setTimeout(() => ctrl.abort(), timeout);
  }

  try {
    const r = await fetch(BASE + path, opts);
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      let detail = err.detail ?? err.message ?? err.error;
      if (Array.isArray(detail)) {
        detail = detail.map(d => (d && (d.msg || d.message)) || (typeof d === 'string' ? d : JSON.stringify(d))).join(', ');
      } else if (detail && typeof detail === 'object') {
        detail = detail.msg || detail.message || JSON.stringify(detail);
      }
      throw new Error(detail || `HTTP ${r.status}`);
    }
    if (r.status === 204) return {};
    return r.json().catch(() => ({}));
  } finally {
    if (to) clearTimeout(to);
  }
}

const _getCache = new Map();

function getCached(path, ttl = 10000, options) {
  const now = Date.now();
  const hit = _getCache.get(path);
  if (hit) {
    if (hit.promise) return hit.promise;
    if (now - hit.ts < ttl) return Promise.resolve(hit.value);
  }
  const promise = request('GET', path, null, options).then(
    (value) => { _getCache.set(path, { value, ts: Date.now() }); return value; },
    (err) => { const h = _getCache.get(path); if (h && h.promise === promise) _getCache.delete(path); throw err; }
  );
  _getCache.set(path, { promise, ts: now });
  return promise;
}

function invalidateCache(path) {
  if (path) _getCache.delete(path); else _getCache.clear();
}

export const api = {
  get:    (path, options)       => request('GET', path, null, options),
  getCached,
  invalidateCache,
  post:   (path, body, options) => request('POST', path, body, options),
  delete: (path, options)       => request('DELETE', path, null, options),

  getAuthStatus: ()            => api.get('/api/auth/status'),
  login:         (pseudo, pwd) => api.post('/api/auth/login', { pseudo, password: pwd }),
  logout:        ()            => api.post('/api/auth/logout'),

  getFavoris:    (refresh = false) => refresh
    ? (api.invalidateCache('/api/anime/favoris'), api.get('/api/anime/favoris?refresh=true', { timeout: 0 }))
    : api.getCached('/api/anime/favoris', 30000),
  recherche:     (q)           => api.get(`/api/anime/recherche?q=${encodeURIComponent(q)}`),
  getEpisodes:   (url)         => api.getCached(`/api/anime/episodes?url=${encodeURIComponent(url)}`, 300000),
  prefetchEpisodes: (url)      => { if (url) api.getCached(`/api/anime/episodes?url=${encodeURIComponent(url)}`, 300000).catch(() => {}); },
  checkUpdates:  (refresh = false) => api.get('/api/anime/check-updates' + (refresh ? '?refresh=true' : ''), { timeout: 0 }),
  coherenceLibrairie: ()       => api.get('/api/anime/coherence-librairie', { timeout: 0 }),
  // Meme TTL que les episodes : sans mise en cache, precharger au survol
  // relancerait simplement la requete au clic. Le « timeout: 0 » d'origine est
  // conserve — cet appel scrape le site et n'a jamais eu de plafond.
  getScanInfo:   (slug, lang = 'vf') => api.getCached(`/api/anime/scan?slug=${encodeURIComponent(slug)}&lang=${encodeURIComponent(lang)}`, 300000, { timeout: 0 }),
  prefetchScan:  (slug, lang = 'vf') => { if (slug) api.getScanInfo(slug, lang).catch(() => {}); },
  getScanPages:  (oeuvre, chap, lang = 'vf') => api.get(`/api/anime/scan-pages?oeuvre=${encodeURIComponent(oeuvre)}&chap=${encodeURIComponent(chap)}&lang=${encodeURIComponent(lang)}`, { timeout: 0 }),
  getScanLocal:  (fichier)     => api.get(`/api/anime/scan-local?fichier=${encodeURIComponent(fichier)}`),
  addScanToQueue:(payload)     => api.post('/api/download/scan', payload),

  getDlStatus:   ()            => api.get('/api/download/status'),
  addToQueue:    (ep, episodes) => api.post('/api/download/episode', { ep, episodes: episodes || [] }),
  cancelDl:      ()            => api.post('/api/download/annuler'),
  dlDirect:      (data)        => api.post('/api/download/direct', data),
};
