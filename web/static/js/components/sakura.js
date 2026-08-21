const _cache = new Map(
  Object.entries(JSON.parse(localStorage.getItem('anilist_covers') || '{}'))
);

let _saveTimer = null;
function _saveCache() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => {
    try {
      const obj = {};
      _cache.forEach((v, k) => { obj[k] = v; });
      localStorage.setItem('anilist_covers', JSON.stringify(obj));
    } catch {}
  }, 1000);
}

function _normalise(nom) {
  return nom.toLowerCase()
    .replace(/\s*(vostfr|vf|vo)\s*$/i, '')
    .replace(/\s+saison\s+\d+/i, '')
    .replace(/\s+season\s+\d+/i, '')
    .trim();
}

async function _fetchAniList(titre) {
  const cle = _normalise(titre);
  if (_cache.has(cle)) return _cache.get(cle);

  const QUERY = `query($s:String){Media(search:$s,type:ANIME){coverImage{large}}}`;
  const ctrl = new AbortController();
  const to   = setTimeout(() => ctrl.abort(), 8000);
  try {
    const r = await fetch('https://graphql.anilist.co', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: QUERY, variables: { s: titre } }),
      signal: ctrl.signal,
    });
    if (!r.ok) return null;
    const data = await r.json();
    const img  = data?.data?.Media?.coverImage?.large || null;
    _cache.set(cle, img);
    _saveCache();
    return img;
  } catch {
    return null;
  } finally {
    clearTimeout(to);
  }
}

function _getTitre(card) {
  return card.querySelector(
    '.anime-card-title, .recent-title, .lib-title, .anime-du-jour-title'
  )?.textContent?.trim() || '';
}

function _replacePlaceholder(phld, url, titre) {
  const img = document.createElement('img');
  img.alt   = titre;
  img.loading = 'lazy';
  img.decoding = 'async';
  img.src   = url;
  if (phld.classList.contains('lib-cover-placeholder')) {
    img.className = 'lib-cover-thumb';
  } else if (phld.classList.contains('recent-cover-placeholder')) {
    img.className = 'recent-cover';
  } else if (phld.classList.contains('anime-du-jour-cover-placeholder')) {
    img.className = 'anime-du-jour-cover';
  } else {
    img.className = 'anime-card-img';
  }
  phld.replaceWith(img);
}

const _pending = new Set();

async function _enrichCard(card) {
  if (card.dataset.anilistDone) return;
  const titre = _getTitre(card);
  if (!titre || _pending.has(titre)) return;

  const phld = card.querySelector(
    '.anime-card-placeholder, .lib-cover-placeholder, .recent-cover-placeholder, .anime-du-jour-cover-placeholder'
  );
  if (!phld) { card.dataset.anilistDone = '1'; return; }

  card.dataset.anilistDone = '1';
  _pending.add(titre);

  const url = await _fetchAniList(titre);
  _pending.delete(titre);

  if (!url) return;

  const stillPhld = card.querySelector(
    '.anime-card-placeholder, .lib-cover-placeholder, .recent-cover-placeholder, .anime-du-jour-cover-placeholder'
  );
  if (stillPhld) _replacePlaceholder(stillPhld, url, titre);
}

function _addOnerror(img, card) {
  if (img.dataset.onerrorAdded) return;
  img.dataset.onerrorAdded = '1';
  img.addEventListener('error', async () => {
    if (card.dataset.anilistErr) return;
    const titre = _getTitre(card);
    if (!titre) return;
    card.dataset.anilistErr = '1';
    const url = await _fetchAniList(titre);
    if (url) img.src = url;
  });
}

const _CARD_SEL = '.anime-card, .recent-card, .lib-anime, .anime-du-jour-card';

let _io = null;
function _ensureIO() {
  if (_io) return _io;
  _io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      const card = e.target;
      _io.unobserve(card);
      _enrichCard(card);
      card.querySelectorAll('img').forEach(img => _addOnerror(img, card));
    }
  }, { rootMargin: '400px 0px' });
  return _io;
}

function _observeNew(root) {
  const io = _ensureIO();
  (root || document).querySelectorAll(_CARD_SEL).forEach(card => {
    if (card.dataset.anilistObs) return;
    card.dataset.anilistObs = '1';
    io.observe(card);
  });
}

let _watchInstalled = false;

export function watchForPlaceholders() {
  _observeNew(document);

  if (_watchInstalled) return;
  _watchInstalled = true;

  const obs = new MutationObserver((mutations) => {
    let relevant = false;
    for (const m of mutations) {
      for (const n of m.addedNodes) {
        if (n.nodeType === 1 && (n.matches?.(_CARD_SEL) || n.querySelector?.(_CARD_SEL))) {
          relevant = true;
          break;
        }
      }
      if (relevant) break;
    }
    if (!relevant) return;
    clearTimeout(obs._t);
    obs._t = setTimeout(() => _observeNew(document), 150);
  });
  obs.observe(document.body, { childList: true, subtree: true });
}
