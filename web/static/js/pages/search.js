import { esc } from '../utils/escape.js';
import { coverSrc } from '../utils/cover.js';
import { softScrollTop } from '../utils/scroll.js';
import { animateCount } from '../utils/anim.js';
import { api }       from '../api.js';
import { openAnime } from '../components/modal.js';
import { toast }     from '../components/toast.js';
import { cleAnime as _normaliser, jetonsRequete, surlignerJetons } from '../utils/texte.js';
import { LISTES, listesDe } from '../utils/listes.js';
import { basculerFiltre } from '../utils/filtres.js';

let _searchSeq = 0;
let _suggSeq   = 0;
let _searchAbort = null;
let _suggAbort   = null;

let _debounce      = null;
let _page          = 0;
const PAGE_SIZE    = 20;
let _lastResults   = [];
let _filtreActif   = '';
let _sortActif     = '';
let _suggIdx       = -1;
let _suggItems     = [];
let _lastQuery     = '';
let _librairie     = new Set();
let _listesParNom  = new Map();
let _vueMode       = localStorage.getItem('search_vue') || 'grid';

const HISTORY_KEY  = 'anime_search_history';
const STATE_KEY    = 'search_last_state';
const MAX_HISTORY  = 8;

export function initSearch() {
  const input     = document.getElementById('search-input');
  const btnSearch = document.getElementById('btn-search');
  const suggsEl   = document.getElementById('search-suggestions');
  if (!input) return;

  _chargerLibrairie();
  initCatalogue();

  if (suggsEl) {
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', 'search-suggestions');
    input.setAttribute('aria-haspopup', 'listbox');
    suggsEl.setAttribute('role', 'listbox');
    suggsEl.setAttribute('aria-label', 'Suggestions de recherche');
    const syncExpanded = () => {
      const open = !suggsEl.classList.contains('hidden');
      input.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (!open) input.removeAttribute('aria-activedescendant');
    };
    new MutationObserver(syncExpanded).observe(suggsEl, { attributes: true, attributeFilter: ['class'] });
    syncExpanded();
  }

  document.querySelector('[data-page="recherche"]')?.addEventListener('click', () => {
    setTimeout(() => {
      input.focus();
      _restaurerEtat();
    }, 120);
  });

  document.addEventListener('keydown', e => {
    if (e.key === '/' && document.activeElement !== input
        && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) {
      e.preventDefault();
      document.querySelector('[data-page="recherche"]')?.click();
    }
  });

  const wrap = input.closest('.search-wrap') || input.parentElement;
  wrap.style.position = 'relative';

  let clearBtn = document.getElementById('search-clear');
  if (!clearBtn) {
    clearBtn = document.createElement('button');
    clearBtn.id = 'search-clear';
    clearBtn.innerHTML = '&times;';
    clearBtn.title = 'Effacer';
    wrap.appendChild(clearBtn);
  }

  _addVueToggle();

  const toggleClear = () => {
    clearBtn.style.display = input.value ? 'flex' : 'none';
  };
  toggleClear();

  clearBtn.addEventListener('click', () => {
    input.value = '';
    _lastQuery   = '';
    _lastResults = [];
    _filtreActif = '';
    _sortActif   = '';
    toggleClear();
    suggsEl?.classList.add('hidden');
    const grid = document.getElementById('search-grid');
    if (grid) { grid.innerHTML = ''; grid.className = _vueMode === 'list' ? 'anime-list' : 'anime-grid'; }
    document.getElementById('search-filters')?.remove();
    _suggIdx = -1; _suggItems = [];
    localStorage.removeItem(STATE_KEY);
    showHistory();
    input.focus();
  });

  input.addEventListener('input', () => {
    toggleClear();
    _suggIdx = -1;
    clearTimeout(_debounce);
    const q = input.value.trim();
    if (!q) { suggsEl?.classList.add('hidden'); showHistory(); return; }
    if (q.length < 2) { suggsEl?.classList.add('hidden'); return; }
    _debounce = setTimeout(() => fetchSuggestions(q), 400);
  });

  input.addEventListener('focus', () => {
    if (!input.value.trim()) setTimeout(showHistory, 60);
  });
  input.addEventListener('click', () => {
    if (!input.value.trim()) setTimeout(showHistory, 60);
  });

  input.addEventListener('keydown', e => {
    if (!suggsEl?.classList.contains('hidden') && _suggItems.length) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        _suggIdx = Math.min(_suggIdx + 1, _suggItems.length - 1);
        _highlightSugg();
        return;
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        _suggIdx = Math.max(_suggIdx - 1, -1);
        _highlightSugg();
        return;
      } else if (e.key === 'Enter' && _suggIdx >= 0) {
        e.preventDefault();
        _suggItems[_suggIdx]?.click();
        return;
      }
    }
    if (e.key === 'Enter')  { suggsEl?.classList.add('hidden'); doSearch(input.value.trim()); }
    if (e.key === 'Escape') { suggsEl?.classList.add('hidden'); _suggIdx = -1; }
  });

  btnSearch?.addEventListener('click', () => doSearch(input.value.trim()));

  document.addEventListener('click', e => {
    if (!e.target.closest('.search-wrap') && !e.target.closest('#btn-search')) {
      suggsEl?.classList.add('hidden');
      _suggIdx = -1;
    }
  });
}

function _tagOptions() {
  _suggItems.forEach((el, i) => {
    el.setAttribute('role', 'option');
    el.setAttribute('aria-selected', 'false');
    if (!el.id) el.id = `sugg-opt-${i}`;
  });
}

function _highlightSugg() {
  const input = document.getElementById('search-input');
  _suggItems.forEach((el, i) => {
    const on = i === _suggIdx;
    el.style.background = on ? 'var(--bg3)' : '';
    el.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  const cur = _suggItems[_suggIdx];
  if (cur) {
    input?.setAttribute('aria-activedescendant', cur.id);
    cur.scrollIntoView({ block: 'nearest' });
  } else {
    input?.removeAttribute('aria-activedescendant');
  }
}

async function _chargerLibrairie() {
  try {
    const r = await api.getCached('/api/anime/librairie', 30000);
    _librairie = new Set((r.animes || []).map(a => _normaliser(a.nom)));
  } catch { _librairie = new Set(); }
  try {
    const f = await api.getFavoris();
    _listesParNom = new Map(
      (f.animes || []).map(a => [_normaliser(a.nom), listesDe(a)]),
    );
  } catch { _listesParNom = new Map(); }
}

function _estTelechargé(nom) {
  return _librairie.has(_normaliser(nom));
}

// Un resultat de recherche ne se filtre pas par liste — on a cherche un titre
// precis. Ce qui manquait, c'est de voir qu'il y est deja.
function _pastillesListes(nom) {
  const ids = _listesParNom.get(_normaliser(nom));
  if (!ids) return '';
  return LISTES
    .filter(l => ids.includes(l.id))
    .map(l => `<span class="res-liste" title="${esc(l.label)}">${l.label.split(' ')[0]}</span>`)
    .join('');
}

function _sauvegarderEtat() {
  if (!_lastQuery || !_lastResults.length) return;
  try {
    sessionStorage.setItem(STATE_KEY, JSON.stringify({
      query:   _lastQuery,
      results: _lastResults,
      filtre:  _filtreActif,
      sort:    _sortActif,
    }));
  } catch {}
}

function _restaurerEtat() {
  try {
    const raw = sessionStorage.getItem(STATE_KEY);
    if (!raw) return;
    const s = JSON.parse(raw);
    if (!s.query || !s.results?.length) return;

    const input = document.getElementById('search-input');
    if (input) {
      input.value = s.query;
      document.getElementById('search-clear').style.display = 'flex';
    }
    _lastQuery   = s.query;
    _lastResults = s.results;
    _filtreActif = s.filtre || '';
    _sortActif   = s.sort   || '';

    renderFilters(_lastResults);
    const liste = _filtreActif ? _lastResults.filter(a => a.statut === _filtreActif) : [..._lastResults];
    if (_sortActif === 'az') liste.sort((a, b) => a.nom.localeCompare(b.nom));
    if (_sortActif === 'za') liste.sort((a, b) => b.nom.localeCompare(a.nom));
    renderResultats(liste, _lastQuery);
  } catch {}
}

function _addVueToggle() {
  const header = document.querySelector('#page-recherche .page-header');
  if (!header || document.getElementById('vue-toggle')) return;

  const btn = document.createElement('button');
  btn.id = 'vue-toggle';
  btn.className = 'vue-toggle';
  btn.title = 'Changer la vue';
  btn.textContent = _vueMode === 'grid' ? '☰ Liste' : '⊞ Grille';
  header.appendChild(btn);

  btn.addEventListener('click', () => {
    _vueMode = _vueMode === 'grid' ? 'list' : 'grid';
    localStorage.setItem('search_vue', _vueMode);
    btn.textContent = _vueMode === 'grid' ? '☰ Liste' : '⊞ Grille';
    const grid = document.getElementById('search-grid');
    grid.className = _vueMode === 'list' ? 'anime-list view-transition' : 'anime-grid view-transition';
  setTimeout(() => grid.classList.remove('view-transition'), 300);
    if (_lastResults.length) {
      const liste = _filtreActif ? _lastResults.filter(a => a.statut === _filtreActif) : [..._lastResults];
      renderResultats(liste, _lastQuery);
    }
  });
}

function getHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); }
  catch { return []; }
}
function addHistory(q) {
  if (!q) return;
  let h = getHistory().filter(x => x !== q);
  h.unshift(q);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(0, MAX_HISTORY)));
}
function removeHistory(q) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(getHistory().filter(x => x !== q)));
}

function showHistory() {
  const suggsEl = document.getElementById('search-suggestions');
  if (!suggsEl) return;
  const hist = getHistory();

  if (!hist.length) {
    suggsEl.innerHTML = `
      <div data-s="padding:12px 14px;font-size:11px;color:var(--muted);text-align:center">
        🔍 Tape pour rechercher · <kbd data-s="background:var(--bg3);border:1px solid var(--border2);border-radius:4px;padding:1px 5px;font-size:10px">/</kbd> focus rapide
      </div>`;
    suggsEl.classList.remove('hidden');
    _suggItems = [];
    return;
  }

  suggsEl.innerHTML = `
    <div data-s="display:flex;align-items:center;justify-content:space-between;padding:8px 12px 4px;border-bottom:1px solid var(--border)">
      <span data-s="font-size:10px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:1px">Recherches récentes</span>
      <button id="clear-all-history" data-s="background:none;border:none;color:var(--muted);font-size:11px;cursor:pointer;padding:0">Tout effacer</button>
    </div>
    ${hist.map(h => `
      <div class="sugg-item hist-item" data-q="${esc(h)}" data-s="justify-content:space-between">
        <div data-s="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
          <span data-s="font-size:14px;color:var(--muted);flex-shrink:0">🕐</span>
          <div data-s="font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(h)}</div>
        </div>
        <button class="hist-del" data-q="${esc(h)}" title="Supprimer" data-s="background:none;border:none;color:var(--muted);font-size:16px;cursor:pointer;padding:0 4px;flex-shrink:0;line-height:1">&times;</button>
      </div>`).join('')}`;

  suggsEl.classList.remove('hidden');

  document.getElementById('clear-all-history')?.addEventListener('click', e => {
    e.stopPropagation();
    localStorage.removeItem(HISTORY_KEY);
    suggsEl.classList.add('hidden');
  });

  suggsEl.querySelectorAll('.hist-del').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      removeHistory(btn.dataset.q);
      showHistory();
    });
  });

  _suggItems = [];
  suggsEl.querySelectorAll('.hist-item').forEach(el => {
    _suggItems.push(el);
    el.addEventListener('click', () => {
      const q = el.dataset.q;
      document.getElementById('search-input').value = q;
      document.getElementById('search-clear').style.display = 'flex';
      suggsEl.classList.add('hidden');
      doSearch(q);
    });
  });
  _tagOptions();
}

async function fetchSuggestions(q) {
  const suggsEl = document.getElementById('search-suggestions');
  if (!suggsEl) return;
  const mySeq = ++_suggSeq;
  if (_suggAbort) { try { _suggAbort.abort(); } catch {} }
  _suggAbort = new AbortController();
  try {
    const r      = await api.get(`/api/anime/recherche?q=${encodeURIComponent(q)}`, { signal: _suggAbort.signal });
    if (mySeq !== _suggSeq) return;
    const animes = (r.animes || []).slice(0, 6);
    if (!animes.length) { suggsEl.classList.add('hidden'); return; }

    suggsEl.innerHTML = animes.map(a => `
      <div class="sugg-item">
        ${a.image
          ? `<img src="${esc(coverSrc(a.image))}" loading="lazy" decoding="async" data-s="width:32px;height:46px;object-fit:cover;border-radius:5px;flex-shrink:0;border:1px solid rgba(255,255,255,.08)">`
          : `<span data-s="font-size:20px;flex-shrink:0;width:32px;text-align:center">🎌</span>`}
        <div data-s="flex:1;min-width:0">
          <div data-s="font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-transform:capitalize;color:var(--text)">${highlight(a.nom, q)}</div>
          <div data-s="display:flex;gap:6px;align-items:center;margin-top:3px">
            ${a.statut ? `<span data-s="font-size:10px;font-weight:700;color:var(--green);background:var(--green-soft);padding:1px 6px;border-radius:99px;border:1px solid var(--green-border)">${esc(a.statut)}</span>` : ''}
            ${_estTelechargé(a.nom) ? `<span data-s="font-size:10px;color:var(--amber)">✅ Téléchargé</span>` : ''}
          </div>
        </div>
      </div>`).join('');

    suggsEl.classList.remove('hidden');
    _suggIdx  = -1;
    _suggItems = [...suggsEl.querySelectorAll('.sugg-item')];
    _tagOptions();

    _suggItems.forEach((el, i) => {
      el.addEventListener('click', () => {
        suggsEl.classList.add('hidden');
        document.getElementById('search-input').value = animes[i].nom;
        document.getElementById('search-clear').style.display = 'flex';
        openAnime(animes[i]);
      });
    });
  } catch (e) {
    if (e?.name === 'AbortError') return;
    suggsEl.classList.add('hidden');
  }
}

async function doSearch(q) {
  if (!q) return;
  _resetCatChips();
  document.getElementById('catalogue-more-btn')?.remove();
  _lastQuery = q;
  _page      = 0;
  addHistory(q);
  _sauvegarderEtat();

  const grid    = document.getElementById('search-grid');
  const suggsEl = document.getElementById('search-suggestions');
  if (!grid) return;

  suggsEl?.classList.add('hidden');
  _filtreActif = '';
  _sortActif   = '';
  document.getElementById('search-filters')?.remove();
  grid.className = _vueMode === 'list' ? 'anime-list view-transition' : 'anime-grid view-transition';
  setTimeout(() => grid.classList.remove('view-transition'), 300);
  renderSkeleton(grid);
  softScrollTop(grid);

  try {
    const mySeq  = ++_searchSeq;
    if (_searchAbort) { try { _searchAbort.abort(); } catch {} }
    _searchAbort = new AbortController();
    const r      = await api.get(`/api/anime/recherche?q=${encodeURIComponent(q)}`, { signal: _searchAbort.signal });
    if (mySeq !== _searchSeq) {
      return;
    }
    _lastResults = r.animes || [];
    _sauvegarderEtat();

    if (!_lastResults.length) {
      grid.innerHTML = `
        <div class="empty-state-premium">
          <div class="empty-visual">🔍</div>
          <div data-s="font-family:var(--font-display);font-size:var(--text-xl);font-weight:800;color:var(--text);margin-bottom:var(--space-2)">Aucun résultat</div>
          <div data-s="color:var(--muted);font-size:var(--text-sm);max-width:320px;margin:0 auto;line-height:1.6">Rien pour « ${esc(q)} » — essaie un titre en japonais ou en anglais.</div>
        </div>`;
      return;
    }

    renderFilters(_lastResults);
    renderResultats(_lastResults, q);
    _animateCounter('results-count', _lastResults.length);

  } catch(e) {
    if (e?.name === 'AbortError') return;
    grid.innerHTML = `<div class="empty-state"><span>❌ ${esc(e.message)}</span></div>`;
    toast(`Erreur recherche : ${e.message}`, 'error');
  }
}

function renderSkeleton(grid) {
  grid.innerHTML = Array(10).fill(0).map(() =>
    _vueMode === 'list'
      ? `<div class="anime-list-item skeleton-card">
           <div class="skeleton-img" data-s="width:48px;height:68px;border-radius:6px;flex-shrink:0"></div>
           <div data-s="flex:1">
             <div class="skeleton-line" data-s="width:60%;margin-bottom:8px"></div>
             <div class="skeleton-line" data-s="width:30%"></div>
           </div>
         </div>`
      : `<div class="anime-card skeleton-card">
           <div class="skeleton-img"></div>
           <div class="anime-card-body">
             <div class="skeleton-line" data-s="width:80%"></div>
             <div class="skeleton-line" data-s="width:40%;margin-top:6px"></div>
           </div>
         </div>`
  ).join('');
}

function renderFilters(animes) {
  document.getElementById('search-filters')?.remove();
  const langues = [...new Set(animes.map(a => a.statut).filter(Boolean))].sort();
  const nbDl    = animes.filter(a => _estTelechargé(a.nom)).length;

  const bar = document.createElement('div');
  bar.id = 'search-filters';
  bar.innerHTML = `
    <span data-s="font-size:11px;color:var(--muted)"><span id="results-count">0</span> résultat${animes.length>1?'s':''}${nbDl ? ` · <span data-s="color:var(--amber)">✅ ${nbDl} téléchargé${nbDl>1?'s':''}</span>` : ''}</span>
    ${langues.length > 1 ? `
      <span data-s="color:var(--border2);margin:0 2px">|</span>
      ${/* « Tous » etait marque actif en dur : une recherche restauree avec un
            filtre de langue affichait ses resultats filtres sous une puce qui
            disait le contraire. */''}
      <button class="fil-btn${!_filtreActif ? ' active' : ''}" data-langue="" aria-pressed="${!_filtreActif}">Tous (${animes.length})</button>
      ${langues.map(l => `<button class="fil-btn${_filtreActif === l ? ' active' : ''}" data-langue="${l}" aria-pressed="${_filtreActif === l}">${l} (${animes.filter(a=>a.statut===l).length})</button>`).join('')}
    ` : ''}
    <span data-s="flex:1"></span>
    <button class="fil-btn sort-btn ${!_sortActif?'active':''}" data-sort="" title="Tri par pertinence">↕ Pertinence</button>
    <button class="fil-btn sort-btn ${_sortActif==='az'?'active':''}" data-sort="az">A→Z</button>
    <button class="fil-btn sort-btn ${_sortActif==='za'?'active':''}" data-sort="za">Z→A</button>`;

  document.getElementById('search-grid').parentElement.insertBefore(bar, document.getElementById('search-grid'));

  // Meme geste que dans la librairie et les favoris : re-cliquer la langue
  // active revient a « Tous ».
  const langBtns = bar.querySelectorAll('.fil-btn:not(.sort-btn)');
  langBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      _filtreActif = basculerFiltre(langBtns, btn, _filtreActif, 'langue');
      applyFiltersSort();
    });
  });

  bar.querySelectorAll('.sort-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      bar.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _sortActif = btn.dataset.sort;
      applyFiltersSort();
    });
  });
}

function applyFiltersSort() {
  let liste = _filtreActif
    ? _lastResults.filter(a => a.statut === _filtreActif)
    : [..._lastResults];
  if (_sortActif === 'az') liste.sort((a, b) => a.nom.localeCompare(b.nom));
  if (_sortActif === 'za') liste.sort((a, b) => b.nom.localeCompare(a.nom));
  renderResultats(liste, _lastQuery);
}

function renderResultats(animes, query = '') {
  const grid = document.getElementById('search-grid');
  if (!grid) return;
  grid.className = _vueMode === 'list' ? 'anime-list' : 'anime-grid';

  document.getElementById('load-more-btn')?.remove();

  const slice   = animes.slice(0, (_page + 1) * PAGE_SIZE);
  const hasMore = animes.length > slice.length;

  if (_vueMode === 'list') {
    grid.innerHTML = slice.map((a, i) => `
      <div class="anime-list-item" role="button" tabindex="0" aria-label="${esc(a.nom)}" data-idx="${i}" data-prefetch="${esc(a.url || '')}">
        ${a.image
          ? `<img src="${esc(coverSrc(a.image))}" loading="lazy" decoding="async" data-s="width:48px;height:68px;object-fit:cover;border-radius:6px;flex-shrink:0">`
          : `<div data-s="width:48px;height:68px;background:var(--bg3);border-radius:6px;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:20px">🎌</div>`}
        <div data-s="flex:1;min-width:0">
          <div data-s="font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${highlight(a.nom, query)}</div>
          <div data-s="display:flex;gap:8px;align-items:center;margin-top:4px">
            ${a.statut ? `<span data-s="font-size:11px;color:var(--green)">${esc(a.statut)}</span>` : ''}
            ${_estTelechargé(a.nom) ? `<span data-s="font-size:11px;color:var(--amber)">✅ Téléchargé</span>` : ''}
            ${_pastillesListes(a.nom)}
          </div>
        </div>
        <button class="anime-card-dl" data-s="flex-shrink:0" title="Voir épisodes">⬇️</button>
      </div>`).join('');

    grid.querySelectorAll('.anime-list-item').forEach((row, i) => {
      row.addEventListener('click', e => {
        if (e.target.classList.contains('anime-card-dl')) return;
        openAnime(slice[i]);
      });
      row.addEventListener('keydown', e => {
        if (e.repeat) return;
        if ((e.key === 'Enter' || e.key === ' ') && e.target === row) {
          e.preventDefault();
          openAnime(slice[i]);
        }
      });
      row.querySelector('.anime-card-dl')?.addEventListener('click', e => {
        e.stopPropagation();
        openAnime(slice[i]);
      });
    });
  } else {
    grid.innerHTML = slice.map((a, i) => `
      <div class="anime-card" role="button" tabindex="0" aria-label="${esc(a.nom)}" data-idx="${i}" data-prefetch="${esc(a.url || '')}" data-s="animation-delay:${Math.min(i, 10) * 30}ms">
        ${_estTelechargé(a.nom) ? `<div class="dl-badge" title="Déjà téléchargé">✅</div>` : ''}
        ${a.image
          ? `<img class="anime-card-img" src="${esc(coverSrc(a.image))}" alt="${esc(a.nom)}" loading="lazy" decoding="async">`
          : `<div class="anime-card-placeholder">🎌</div>`}
        <div class="anime-card-body">
          <div class="anime-card-title">${highlight(a.nom, query)}</div>
          ${a.statut ? `<span data-s="font-size:10px;color:var(--green)">${esc(a.statut)}</span>` : ''}
          ${_pastillesListes(a.nom)}
        </div>
        <button class="anime-card-dl" title="Voir épisodes">⬇️</button>
      </div>`).join('');

    grid.querySelectorAll('.anime-card').forEach((card, i) => {
      card.addEventListener('click', e => {
        if (e.target.classList.contains('anime-card-dl')) return;
        openAnime(slice[i]);
      });
      card.addEventListener('keydown', e => {
        if (e.repeat) return;
        if ((e.key === 'Enter' || e.key === ' ') && e.target === card) {
          e.preventDefault();
          openAnime(slice[i]);
        }
      });
      card.querySelector('.anime-card-dl')?.addEventListener('click', e => {
        e.stopPropagation();
        openAnime(slice[i]);
      });
    });
  }

  if (hasMore) {
    const btn = document.createElement('button');
    btn.id        = 'load-more-btn';
    btn.className = 'load-more-btn';
    btn.textContent = `Charger plus (${animes.length - slice.length} restants)`;
    btn.addEventListener('click', () => {
      _page++;
      renderResultats(animes, query);
    });
    grid.insertAdjacentElement('afterend', btn);
  }
}

function _animateCounter(id, target) { animateCount(document.getElementById(id), target); }

// Le moteur du site rend « Pokémon » pour la requete « pokemon » : surligner
// par sous-chaine brute ne trouvait rien et laissait le titre sans marque.
function highlight(text, query) {
  return surlignerJetons(
    text,
    jetonsRequete(query),
    '<mark data-s="background:rgba(74,143,232,.35);color:var(--rem);border-radius:3px;padding:0 1px">',
    '</mark>',
  );
}

const CAT_TYPES   = ['Anime', 'Film', 'Scans'];
const CAT_LANGUES = ['VOSTFR', 'VF'];
let _catGenre = '', _catType = '', _catLangue = '', _catPage = 1;

function _catChip(label, active) {
  return `<button class="cat-chip" type="button" data-s="font-size:11px;font-weight:700;padding:5px 12px;border-radius:99px;cursor:pointer;font-family:inherit;transition:all .2s;border:1px solid ${active ? 'transparent' : 'var(--border2)'};background:${active ? 'linear-gradient(135deg,var(--rem),var(--ram))' : 'var(--bg3)'};color:${active ? '#fff' : 'var(--muted)'}">${esc(label)}</button>`;
}

function _renderCatChips() {
  const t = document.getElementById('cat-types');
  const l = document.getElementById('cat-langues');
  if (t) {
    t.innerHTML = CAT_TYPES.map(x => _catChip(x, _catType === x)).join('');
    t.querySelectorAll('.cat-chip').forEach((b, i) => b.addEventListener('click', () => {
      _catType = _catType === CAT_TYPES[i] ? '' : CAT_TYPES[i];
      _renderCatChips(); _lancerBrowse();
    }));
  }
  if (l) {
    l.innerHTML = CAT_LANGUES.map(x => _catChip(x, _catLangue === x)).join('');
    l.querySelectorAll('.cat-chip').forEach((b, i) => b.addEventListener('click', () => {
      _catLangue = _catLangue === CAT_LANGUES[i] ? '' : CAT_LANGUES[i];
      _renderCatChips(); _lancerBrowse();
    }));
  }
}

function _resetCatChips() {
  _catGenre = ''; _catType = ''; _catLangue = '';
  const sel = document.getElementById('cat-genre');
  if (sel) sel.value = '';
  _renderCatChips();
  const cc = document.getElementById('cat-clear');
  if (cc) cc.style.display = 'none';
}

async function initCatalogue() {
  const bar = document.getElementById('catalogue-bar');
  if (!bar) return;
  try {
    const g = await api.getCached('/api/anime/catalogue-genres', 600000);
    const sel = document.getElementById('cat-genre');
    if (sel && Array.isArray(g.genres)) {
      sel.insertAdjacentHTML('beforeend', g.genres.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join(''));
    }
  } catch {}
  _renderCatChips();
  document.getElementById('cat-genre')?.addEventListener('change', e => {
    _catGenre = e.target.value; _lancerBrowse();
  });
  document.getElementById('cat-clear')?.addEventListener('click', () => {
    _resetCatChips();
    const grid = document.getElementById('search-grid');
    if (grid) grid.innerHTML = '';
    document.getElementById('catalogue-more-btn')?.remove();
    _lastResults = [];
  });
}

function _lancerBrowse() {
  const cc = document.getElementById('cat-clear');
  if (!_catGenre && !_catType && !_catLangue) {
    if (cc) cc.style.display = 'none';
    const grid = document.getElementById('search-grid');
    if (grid) grid.innerHTML = '';
    document.getElementById('catalogue-more-btn')?.remove();
    _lastResults = [];
    return;
  }
  if (cc) cc.style.display = 'inline-block';
  _catPage = 1;
  browseCatalogue(false);
}

async function browseCatalogue(append) {
  const grid = document.getElementById('search-grid');
  if (!grid) return;
  if (!append) {
    _lastResults = []; _lastQuery = ''; _page = 999;
    document.getElementById('search-filters')?.remove();
    document.getElementById('search-suggestions')?.classList.add('hidden');
    renderSkeleton(grid);
  }
  try {
    const qs = new URLSearchParams();
    if (_catGenre)  qs.set('genre', _catGenre);
    if (_catType)   qs.set('type', _catType);
    if (_catLangue) qs.set('langue', _catLangue);
    qs.set('page', String(_catPage));
    const r = await api.get(`/api/anime/catalogue?${qs.toString()}`, { timeout: 0 });
    const animes = r.animes || [];
    _lastResults = append ? _lastResults.concat(animes) : animes;
    document.getElementById('catalogue-more-btn')?.remove();
    if (!_lastResults.length) {
      grid.innerHTML = '<div class="empty-state-premium"><div class="empty-visual">📚</div><div data-s="color:var(--muted);font-size:var(--text-sm)">Aucun anime pour ces filtres</div></div>';
      return;
    }
    _page = 999;
    renderResultats(_lastResults, '');
    if (animes.length >= 40) {
      const btn = document.createElement('button');
      btn.id = 'catalogue-more-btn';
      btn.className = 'load-more-btn';
      btn.textContent = 'Page suivante ▶';
      btn.addEventListener('click', () => { _catPage++; browseCatalogue(true); });
      grid.insertAdjacentElement('afterend', btn);
    }
  } catch (e) {
    if (e?.name === 'AbortError') return;
    toast(`Erreur catalogue : ${e.message}`, 'error');
    if (!append) {
      grid.innerHTML = '<div class="empty-state-premium"><div class="empty-visual">❌</div><div data-s="color:var(--muted);font-size:var(--text-sm)">Impossible de charger le catalogue. Vérifie ta connexion et réessaie.</div></div>';
    }
  }
}
