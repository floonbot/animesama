import { esc } from '../utils/escape.js';
import { coverSrc } from '../utils/cover.js';
import { animateCount } from '../utils/anim.js';
import { api } from '../api.js';
import { openAnime } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { slugFromUrl } from '../utils/slug.js';
import { basculerFiltre } from '../utils/filtres.js';
import { SUJET_LIBRAIRIE, SUJET_REGLAGES, abonnerVue } from '../utils/vue-live.js';
import {
  cleAnime, correspond, jetonsRequete, normaliserTexte, rang, surlignerJetons,
} from '../utils/texte.js';
import {
  LISTE_DEFAUT, compter, dansListe, libelleListe, listesPresentes,
} from '../utils/listes.js';

// « jamais choisi » et « a choisi Defaut » etaient indistinguables tant que le
// bouton Defaut ecrivait la chaine vide : `'' || defaut` rend le defaut. La
// distinction existe pourtant deja dans localStorage — getItem rend `null`
// pour une cle absente et `''` pour une valeur vide. On lit donc la cle brute,
// et « Defaut » porte desormais un identifiant a lui.
const TRI_DEFAUT_INITIAL = 'dl';

function _triInitial() {
  const brut = localStorage.getItem('fav_sort');
  if (brut === null) return TRI_DEFAUT_INITIAL;
  if (brut === '') return 'defaut';
  return brut;
}

let _allAnimes = [];
let _librairie = new Set();
let _libScans = new Set();
let _libVideo = new Set();
// Reconstruire la barre d'outils remet le champ a vide : un rafraichissement
// vivant effacerait la frappe en cours si l'etat ne vivait que dans le DOM.
let _recherche = '';
let _filtreActif = localStorage.getItem('fav_filtre') || '';
let _sortActif = _triInitial();
let _listeActive = localStorage.getItem('fav_liste') || LISTE_DEFAUT;
let _vueMode = localStorage.getItem('fav_vue') || 'grid';
let _typeActif = localStorage.getItem('fav_type') || 'anime';
let _typesDetectes = false;
let _typesEnCours  = false;
let _stateLoaded = false;

// v5 : le serveur classait toute fiche « both » (les gabarits et les sections
// en commentaire comptaient comme des panneaux). Relire la v4 garderait ce tri
// faux sans jamais redemander.
const FAV_TYPES_KEY = 'fav_types_v5';
try { localStorage.removeItem('fav_types_v4'); } catch {}
let _typesMap = {};
try { _typesMap = JSON.parse(localStorage.getItem(FAV_TYPES_KEY)) || {}; } catch { _typesMap = {}; }
function _saveTypes() { try { localStorage.setItem(FAV_TYPES_KEY, JSON.stringify(_typesMap)); } catch {} }
function _applyTypes() {
  let known = 0;
  for (const a of _allAnimes) {
    if (a.url && _typesMap[a.url]) { a.type = _typesMap[a.url]; known++; }
  }
  if (_allAnimes.length && known >= _allAnimes.length) _typesDetectes = true;
}

let _loading = false;

let _renderedList = [];
let _favFirstRender = true;
let _renderToken = 0;

function _debounce(fn, ms) {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// v2 : les cles de rapprochement librairie repliaient les accents apres coup.
// Reutiliser un cache v1 rendrait de faux « deja telecharge ».
// v3 : la charge utile porte les quatre listes du compte, pas les seuls
// favoris. Un cache v2 relu tel quel masquerait les puces jusqu'a la
// revalidation, tout etant compte comme favori.
// v4 : chaque anime y porte son type, faux en v3 (voir FAV_TYPES_KEY).
const FAV_CACHE_KEY = 'fav_cache_v4';
let _revalidating = false;

// Normaliser a chaque frappe et par anime annulerait le gain du filtrage :
// l'index se reconstruit quand le tableau change d'identite, pas avant.
let _indexNoms = null;
let _indexSource = null;

function _indexRecherche() {
  if (_indexNoms && _indexSource === _allAnimes) return _indexNoms;
  const index = new Map();
  for (const a of _allAnimes) index.set(a, normaliserTexte(a.nom));
  _indexNoms = index;
  _indexSource = _allAnimes;
  return index;
}

function _saveFavCache() {
  try {
    sessionStorage.setItem(FAV_CACHE_KEY, JSON.stringify({
      animes: _allAnimes, lib: [..._librairie], libScans: [..._libScans], libVideo: [..._libVideo],
    }));
  } catch {}
}
function _loadFavCache() {
  try {
    const raw = sessionStorage.getItem(FAV_CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}
function _favSignature(animes, lib) {
  return animes.map(a => `${a.url}|${a.image}|${a.type || ''}`).join(',') + '#' + [...lib].sort().join(',');
}

async function _fetchFavoris(forceRefresh) {
  const [favR, libR] = await Promise.allSettled([
    api.getFavoris(forceRefresh),
    api.getCached('/api/anime/librairie', 30000),
  ]);
  const animes = favR.status === 'fulfilled' ? (favR.value.animes || []) : [];
  const libAnimes = libR.status === 'fulfilled' ? (libR.value.animes || []) : [];
  return {
    animes, ..._setsLibrairie(libAnimes), favOk: favR.status === 'fulfilled',
  };
}

function _setsLibrairie(libAnimes) {
  const lib = new Set(), libScans = new Set(), libVideo = new Set();
  for (const a of libAnimes) {
    const n = cleAnime(a.nom);
    lib.add(n);
    const eps = (a.saisons || []).flatMap(s => s.episodes || []);
    if (eps.some(e => e.scan)) libScans.add(n);
    if (eps.some(e => !e.scan)) libVideo.add(n);
  }
  return { lib, libScans, libVideo };
}

function _syncCovers() {
  if (!_allAnimes.some(a => a.image)) return;
  api.getCached('/api/anime/covers', 60000).then(connus => {
    const nouveaux = {};
    _allAnimes.forEach(a => { if (a.image && connus[a.nom] !== a.image) nouveaux[a.nom] = a.image; });
    if (Object.keys(nouveaux).length) {
      api.post('/api/anime/covers', { covers: nouveaux }).catch(() => {});
      api.invalidateCache('/api/anime/covers');
    }
  }).catch(() => {});
}

// La charge utile porte l'union des listes ; le compteur du tableau de bord,
// lui, a toujours voulu dire « favoris » et doit continuer a le dire.
function _nbFavoris() {
  return compter(_allAnimes, LISTE_DEFAUT);
}

function _animesDeLaListe() {
  return _allAnimes.filter(a => dansListe(a, _listeActive));
}

function _renderFav(grid, statEl, animate) {
  const nbFav = _nbFavoris();
  if (statEl) {
    if (animate) _animateStat(statEl, nbFav);
    else statEl.textContent = nbFav;
  }
  if (!_allAnimes.length) {
    grid.innerHTML = `<div class="empty-state"><span class="empty-icon">⭐</span><span>Aucun favori trouvé</span></div>`;
    return;
  }
  _renderToolbar(grid);
  _renderCards();
}

export async function loadFavoris(forceRefresh = false) {
  const grid = document.getElementById('favoris-grid');
  const statEl = document.getElementById('stat-fav');

  if (!grid) return;
  _favFirstRender = true;

  if (_loading) return;

  if (_stateLoaded && _allAnimes.length && !forceRefresh) {
    _renderCards();
    _ensureTypesDetectes();
    return;
  }

  if (!forceRefresh && !_stateLoaded) {
    const cached = _loadFavCache();
    if (cached && Array.isArray(cached.animes) && cached.animes.length) {
      _allAnimes = cached.animes;
      _librairie = new Set(cached.lib || []);
      _libScans = new Set(cached.libScans || []);
      _libVideo = new Set(cached.libVideo || []);
      _applyTypes();
      _stateLoaded = true;
      _renderFav(grid, statEl, false);
      _ensureTypesDetectes();
      _revalidateFavoris(grid, statEl);
      return;
    }
  }

  _loading = true;
  _vueFav.marquerPropre();
  _renderSkeleton(grid);

  try {
    const { animes, lib, libScans, libVideo } = await _fetchFavoris(forceRefresh);
    _allAnimes = animes;
    _librairie = lib;
    _libScans = libScans;
    _libVideo = libVideo;
    _applyTypes();
    _stateLoaded = true;
    _renderFav(grid, statEl, true);
    _ensureTypesDetectes();
    _syncCovers();
    _saveFavCache();
  } catch (e) {
    grid.innerHTML = `<div class="empty-state"><span>❌ ${esc(e.message)}</span></div>`;
    toast(`Erreur favoris : ${e.message}`, 'error');
  } finally {
    _loading = false;
  }
}

// Les favoris eux-memes viennent du site et ne bougent pas parce qu'un episode
// se termine : seuls les marqueurs « deja telecharge » et le compteur changent.
// On ne refait donc que la partie librairie, puis on redessine.
async function _rafraichirEtatTelecharge() {
  const grid = document.getElementById('favoris-grid');
  if (!grid || !_allAnimes.length) return;
  let libAnimes = [];
  try {
    libAnimes = (await api.getCached('/api/anime/librairie', 30000))?.animes || [];
  } catch { return; }
  const lib = new Set(), libScans = new Set(), libVideo = new Set();
  for (const a of libAnimes) {
    const n = cleAnime(a.nom);
    lib.add(n);
    const eps = (a.saisons || []).flatMap(s => s.episodes || []);
    if (eps.some(e => e.scan)) libScans.add(n);
    if (eps.some(e => !e.scan)) libVideo.add(n);
  }
  _librairie = lib;
  _libScans = libScans;
  _libVideo = libVideo;
  _saveFavCache();
  _renderFav(grid, document.getElementById('stat-fav'), false);
}

const _vueFav = abonnerVue({
  page: 'favoris',
  sujets: [SUJET_LIBRAIRIE, SUJET_REGLAGES],
  rafraichir: _rafraichirEtatTelecharge,
});

async function _revalidateFavoris(grid, statEl) {
  if (_revalidating) return;
  _revalidating = true;
  try {
    const { animes, lib, libScans, libVideo, favOk } = await _fetchFavoris(false);
    if (!favOk) return;
    const sigOld = _favSignature(_allAnimes, _librairie);
    const sigNew = _favSignature(animes, lib);
    _allAnimes = animes;
    _librairie = lib;
    _libScans = libScans;
    _libVideo = libVideo;
    _applyTypes();
    _saveFavCache();
    _syncCovers();
    if (sigOld !== sigNew) {
      _favFirstRender = false;
      _renderFav(grid, statEl, false);
    }
  } catch {} finally {
    _revalidating = false;
  }
}

function _renderToolbar(grid) {
  const container = grid.parentElement || grid;

  document.getElementById('fav-toolbar')?.remove();
  const toolbar = document.createElement('div');
  toolbar.id = 'fav-toolbar';
  toolbar.className = 'fav-toolbar';

  const deLaListe = _animesDeLaListe();
  const langues = [...new Set(deLaListe.map(a => a.statut).filter(Boolean))].sort();
  const _dlSet = _typeActif === 'scan' ? _libScans : _libVideo;
  const nbDl = deLaListe.filter(a => _dlSet.has(cleAnime(a.nom))).length;

  const nbAnimes = deLaListe.filter(a => (a.type || 'anime') !== 'scan').length;
  const nbScans  = deLaListe.filter(a => a.type === 'scan' || a.type === 'both').length;
  const scanCountLabel = _typesDetectes ? String(nbScans) : '?';
  const animeCountLabel = _typesDetectes ? String(nbAnimes) : String(deLaListe.length);
  const presentes = listesPresentes(_allAnimes);

  toolbar.innerHTML = `
    <div class="fav-toolbar-left">

      <div class="fav-type-tabs">
        <button class="fav-type-tab ${_typeActif !== 'scan' ? 'active' : ''}" data-type="anime">
          🎬 Animes <span class="fav-type-count">${animeCountLabel}</span>
        </button>
        <button class="fav-type-tab ${_typeActif === 'scan' ? 'active' : ''}" data-type="scan">
          📖 Scans <span class="fav-type-count">${scanCountLabel}</span>
        </button>
      </div>
      <div class="fav-search-wrap">
        <input type="text" id="fav-search" class="fav-search-input" placeholder="🔍 Filtrer…" value="${esc(_recherche)}">
        <button id="fav-search-clear" class="fav-search-clear${_recherche ? '' : ' hidden'}">×</button>
      </div>
      <div data-s="font-size:11px;color:var(--muted);white-space:nowrap">
        <span id="fav-counter">${deLaListe.length} favoris</span>
        ${nbDl ? `<span data-s="color:var(--green)"> · ✅ ${nbDl} téléchargé${nbDl > 1 ? 's' : ''}</span>` : ''}
      </div>
    </div>
    <div class="fav-toolbar-right">
      ${presentes.length ? `
        <div class="fav-liste-btns" role="group" aria-label="Listes du compte">
          ${presentes.map(l => `<button class="fav-filter-btn fav-liste-btn ${_listeActive === l.id ? 'active' : ''}" data-liste="${esc(l.id)}"${_listeActive === l.id ? ' aria-pressed="true"' : ' aria-pressed="false"'}>${esc(l.label)} (${l.n})</button>`).join('')}
        </div>
      ` : ''}
      ${langues.length > 1 ? `
        <div class="fav-lang-btns">
          <button class="fav-filter-btn ${!_filtreActif ? 'active' : ''}" data-langue="" aria-pressed="${!_filtreActif}">Tous</button>
          ${langues.map(l => `<button class="fav-filter-btn ${_filtreActif === l ? 'active' : ''}" data-langue="${esc(l)}" aria-pressed="${_filtreActif === l}">${esc(l)} (${deLaListe.filter(a => a.statut === l).length})</button>`).join('')}
        </div>
      ` : ''}
      <div class="fav-sort-btns">
        <button class="fav-sort-btn ${_sortActif === 'defaut' ? 'active' : ''}" data-sort="defaut">Défaut</button>
        <button class="fav-sort-btn ${_sortActif === 'az' ? 'active' : ''}" data-sort="az">A→Z</button>
        <button class="fav-sort-btn ${_sortActif === 'za' ? 'active' : ''}" data-sort="za">Z→A</button>
        <button class="fav-sort-btn ${_sortActif === 'dl' ? 'active' : ''}" data-sort="dl" title="Téléchargés en premier">✅ D'abord</button>
      </div>
      <button class="fav-vue-btn" id="fav-vue-toggle">${_vueMode === 'list' ? '⊞ Grille' : '☰ Liste'}</button>
    </div>`;

  container.insertBefore(toolbar, grid);
  _bindToolbarEvents();
}

let _favKeydownHandler = null;

function _bindToolbarEvents() {
  if (_favKeydownHandler) {
    document.removeEventListener('keydown', _favKeydownHandler);
  }
  _favKeydownHandler = e => {
    if (e.key === '/' &&
      !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName) &&
      document.getElementById('page-favoris')?.classList.contains('active')) {
      e.preventDefault();
      document.getElementById('fav-search')?.focus();
    }
  };
  document.addEventListener('keydown', _favKeydownHandler);

  document.querySelectorAll('.fav-type-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.fav-type-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _typeActif = btn.dataset.type;
      localStorage.setItem('fav_type', _typeActif);
      if (_typeActif === 'scan' && !_typesDetectes) {
        _detecterTypesScans();
      } else {
        _renderCards();
      }
    });
  });

  const searchInput = document.getElementById('fav-search');
  const searchClear = document.getElementById('fav-search-clear');

  const _appliquerRecherche = _debounce(_renderCards, 160);
  searchInput?.addEventListener('input', () => {
    _recherche = searchInput.value;
    searchClear?.classList.toggle('hidden', !_recherche);
    _appliquerRecherche();
  });

  searchClear?.addEventListener('click', () => {
    searchInput.value = '';
    _recherche = '';
    searchClear.classList.add('hidden');
    _renderCards();
  });

  document.querySelectorAll('.fav-liste-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.dataset.liste === _listeActive) return;
      _listeActive = btn.dataset.liste;
      localStorage.setItem('fav_liste', _listeActive);
      // Les langues et les compteurs de type dependent de la liste regardee :
      // la barre entiere se rejoue, pas seulement les cartes.
      _filtreActif = '';
      localStorage.setItem('fav_filtre', '');
      const grid = document.getElementById('favoris-grid');
      if (grid) _renderToolbar(grid);
      _renderCards();
    });
  });

  // Meme geste que dans la librairie : re-cliquer la langue active revient a
  // « Tous ». Les puces de listes, elles, n'ont pas d'option neutre — les
  // desarmer ne renverrait sur aucune liste.
  const langBtns = document.querySelectorAll('.fav-lang-btns .fav-filter-btn');
  langBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      _filtreActif = basculerFiltre(langBtns, btn, _filtreActif, 'langue');
      localStorage.setItem('fav_filtre', _filtreActif);
      _renderCards();
    });
  });

  document.querySelectorAll('.fav-sort-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.fav-sort-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _sortActif = btn.dataset.sort;
      localStorage.setItem('fav_sort', _sortActif);
      _renderCards();
    });
  });

  document.getElementById('fav-vue-toggle')?.addEventListener('click', function () {
    _vueMode = _vueMode === 'list' ? 'grid' : 'list';
    localStorage.setItem('fav_vue', _vueMode);
    this.textContent = _vueMode === 'list' ? '⊞ Grille' : '☰ Liste';
    _renderCards();
  });
}

function _ensureTypesDetectes() {
  if (_typesDetectes || _typesEnCours || !_allAnimes.length) return;
  _detecterTypesScans(true);
}

async function _detecterTypesScans(silent = false) {
  if (_typesEnCours) return;
  _typesEnCours = true;

  const grid = document.getElementById('favoris-grid');
  if (!silent && grid) {
    grid.className = 'anime-grid';
    grid.innerHTML = `<div class="empty-state">
      <span class="empty-icon">⏳</span>
      <span>Analyse de tes favoris pour trouver les scans…<br>
      <small data-s="color:var(--muted)">(une seule fois, ça peut prendre quelques secondes)</small></span>
    </div>`;
  }

  try {
    const urls = _allAnimes.map(a => a.url).filter(Boolean);
    const r = await api.post('/api/anime/types-favoris', { urls });
    const types = r?.types || {};
    _allAnimes.forEach(a => {
      const t = types[a.url];
      if (t) { a.type = t; _typesMap[a.url] = t; }
    });
    _typesDetectes = true;
    _saveTypes();
    _saveFavCache();
  } catch (e) {
    if (!silent) toast(`Impossible d'analyser les scans : ${e.message}`, 'error');
  } finally {
    _typesEnCours = false;
  }

  const grid2 = document.getElementById('favoris-grid');
  if (grid2) _renderToolbar(grid2);
  _renderCards();
}

function _renderCards() {
  const grid = document.getElementById('favoris-grid');
  const counterEl = document.getElementById('fav-counter');
  if (!grid) return;

  const jetons = jetonsRequete(_recherche);
  const query = jetons.length ? jetons : null;

  let list = _animesDeLaListe();

  if (_typeActif === 'scan') list = list.filter(a => a.type === 'scan' || a.type === 'both');
  else                       list = list.filter(a => (a.type || 'anime') !== 'scan');

  if (_filtreActif) list = list.filter(a => a.statut === _filtreActif);
  const index = jetons.length ? _indexRecherche() : null;
  if (index) list = list.filter(a => correspond(index.get(a) || '', jetons));

  // Le classement de pertinence reste utile meme sous un tri : il departage
  // les ex aequo au lieu de laisser l'ordre du site decider.
  const parRang = index
    ? (a, b) => rang(index.get(a) || '', jetons) - rang(index.get(b) || '', jetons)
    : () => 0;

  const _dlSet = _typeActif === 'scan' ? _libScans : _libVideo;
  const estDl = a => (_dlSet.has(cleAnime(a.nom)) ? 1 : 0);

  if (_sortActif === 'az') list.sort((a, b) => a.nom.localeCompare(b.nom));
  else if (_sortActif === 'za') list.sort((a, b) => b.nom.localeCompare(a.nom));
  else if (_sortActif === 'dl') list.sort((a, b) => (estDl(b) - estDl(a)) || parRang(a, b));
  else if (index) list.sort(parRang);

  const listeLbl = libelleListe(_listeActive).replace(/^\S+\s/, '').toLowerCase();
  if (counterEl) {
    const typeLbl = _typeActif === 'scan' ? 'scan' : 'anime';
    if (query || _filtreActif) {
      counterEl.textContent = `${list.length} résultat${list.length > 1 ? 's' : ''}`;
      counterEl.style.color = 'var(--rem2)';
    } else {
      counterEl.textContent = `${list.length} ${typeLbl}${list.length > 1 ? 's' : ''} · ${listeLbl}`;
      counterEl.style.color = '';
    }
  }

  if (!list.length) {
    const vide = _typeActif === 'scan'
      ? `Aucun scan/manga dans « ${listeLbl} »`
      : (query || _filtreActif ? 'Aucun résultat' : `Aucun anime dans « ${listeLbl} »`);
    grid.innerHTML = `<div class="empty-state"><span class="empty-icon">${_typeActif === 'scan' ? '📖' : '🔍'}</span><span>${esc(vide)}</span></div>`;
    return;
  }

  _renderedList = list;
  grid.className = _vueMode === 'list' ? 'fav-list' : 'anime-grid';

  const token = ++_renderToken;
  const FIRST = 30;
  grid.innerHTML = list.slice(0, FIRST).map((a, i) => _cardHTML(a, i, jetons)).join('');
  _bindFavDelegation(grid);
  _favFirstRender = false;

  if (list.length > FIRST) {
    let i = FIRST;
    const CHUNK = 120;
    const step = () => {
      if (token !== _renderToken) return;
      const next = Math.min(i + CHUNK, list.length);
      grid.insertAdjacentHTML('beforeend', list.slice(i, next).map((a, j) => _cardHTML(a, i + j, jetons)).join(''));
      i = next;
      if (i < list.length) _scheduleChunk(step);
    };
    _scheduleChunk(step);
  }
}

function _scheduleChunk(cb) {
  if (window.requestIdleCallback) window.requestIdleCallback(cb);
  else window.requestAnimationFrame(cb);
}

// Un scan n'ouvre pas la fiche d'episodes mais la liste des chapitres : il se
// precharge donc par son slug, pas par son URL.
function _attrPrefetch(a) {
  if (_typeActif === 'scan') {
    const slug = slugFromUrl(a.url);
    return slug ? ` data-prefetch-scan="${esc(slug)}"` : '';
  }
  return a.url ? ` data-prefetch="${esc(a.url)}"` : '';
}

function _cardHTML(a, i, jetons) {

  const dl = (_typeActif === 'scan' ? _libScans : _libVideo).has(cleAnime(a.nom));
  const animStyle = _favFirstRender ? `animation-delay:${Math.min(i, 10) * 25}ms` : 'animation:none';
  if (_vueMode === 'list') {
    return `
        <div class="fav-list-item" role="button" tabindex="0" aria-label="${esc(a.nom)}" data-idx="${i}"${_attrPrefetch(a)} data-s="${animStyle}">
          ${a.image
          ? `<img src="${esc(coverSrc(a.image))}" class="fav-list-cover" alt="${esc(a.nom)}" loading="lazy" decoding="async">`
          : `<div class="fav-list-cover" data-s="background:var(--bg3);display:flex;align-items:center;justify-content:center;font-size:18px">🎌</div>`}
          <div class="fav-list-info">
            <div class="fav-list-title">${_highlight(a.nom, jetons)}</div>
            <div data-s="display:flex;gap:8px;align-items:center;margin-top:4px">
              ${a.statut ? `<span data-s="font-size:11px;color:var(--green)">${esc(a.statut)}</span>` : ''}
              ${dl ? `<span data-s="font-size:11px;color:var(--amber)">✅ Téléchargé</span>` : ''}
            </div>
          </div>
          <button class="anime-card-dl fav-dl-btn" title="Voir épisodes">⬇️</button>
        </div>`;
  }
  return `
        <div class="anime-card" role="button" tabindex="0" aria-label="${esc(a.nom)}" data-idx="${i}"${_attrPrefetch(a)} data-s="${animStyle}">
          ${dl ? `<div class="dl-badge">✅</div>` : ''}
          ${a.image
          ? `<img class="anime-card-img" src="${esc(coverSrc(a.image))}" alt="${esc(a.nom)}" loading="lazy" decoding="async">`
          : `<div class="anime-card-placeholder">🎌</div>`}
          <div class="anime-card-body">
            <div class="anime-card-title">${_highlight(a.nom, jetons)}</div>
            ${a.statut ? `<span data-s="font-size:10px;color:var(--green)">${esc(a.statut)}</span>` : ''}
          </div>
          <button class="anime-card-dl" title="Voir épisodes">⬇️</button>
        </div>`;
}

async function _activateFavCard(card) {
  const idx = parseInt(card.dataset.idx, 10);
  const anime = _renderedList[idx];
  if (!anime) return;

  if (_typeActif === 'scan') {
    const { slugFromUrl, openScansModal } = await import('./scans.js');
    openScansModal(slugFromUrl(anime.url), anime.nom, anime.image || '');
    return;
  }
  openAnime(anime);
}

function _bindFavDelegation(grid) {
  if (grid._favBound) return;
  grid._favBound = true;
  grid.addEventListener('click', (e) => {
    const card = e.target.closest('.anime-card, .fav-list-item');
    if (card) _activateFavCard(card);
  });
  grid.addEventListener('keydown', (e) => {
    if (e.repeat) return;
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const card = e.target.closest('.anime-card, .fav-list-item');
    if (card && e.target === card) {
      e.preventDefault();
      _activateFavCard(card);
    }
  });
}

function _renderSkeleton(grid) {
  grid.innerHTML = Array(12).fill(0).map(() => `
    <div class="anime-card skeleton-card">
      <div class="skeleton-img" data-s="aspect-ratio:2/3"></div>
      <div class="anime-card-body">
        <div class="skeleton-line" data-s="width:80%;margin-bottom:6px"></div>
        <div class="skeleton-line" data-s="width:40%"></div>
      </div>
    </div>`).join('');
}

function _animateStat(el, target) { animateCount(el, target); }

const MARK_OUVRE =
  '<mark data-s="background:rgba(74,143,232,.35);color:var(--rem2);border-radius:3px;padding:0 1px">';

function _highlight(text, jetons) {
  return surlignerJetons(text, jetons, MARK_OUVRE, '</mark>');
}
