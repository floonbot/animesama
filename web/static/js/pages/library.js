import { esc } from '../utils/escape.js';
import { animateCount } from '../utils/anim.js';
import { api }        from '../api.js';
import { toast }      from '../components/toast.js';
import { correspond, jetonsRequete, normaliserTexte } from '../utils/texte.js';
import { basculerFiltre } from '../utils/filtres.js';
import {
  SUJET_LIBRAIRIE, SUJET_REGLAGES, abonnerVue, signalerChangement,
} from '../utils/vue-live.js';
import { LISTE_DEFAUT, filtrerListe, listesDe, listesPresentes } from '../utils/listes.js';
import {
  _fmtDuree,
  highlight, detectLangue, _normalise, slugify,
} from './library/format.js';
import {
  NAMES_KEY,
  _getFavs, _getNames, _getOpen, _saveFavs, _saveOpen,
} from './library/storage.js';
import './library/player.js';
// Stats et Export ont demenage sur la page Diagnostic : ils y voisinent les
// autres chiffres de l'installation, et la barre d'outils de la librairie
// portait onze boutons.
import { state } from './library/state.js';
import { detectMissingEps } from './library/missing.js';
import {
  checkNouveauxEpisodes, injectUpdateBadges, majStatNouveaux,
  showUpdatesModal, telechargerNouveauxEpisodes,
} from './library/updates.js';
import { openNetflixModal } from './library/netflix.js';
import { confirmSuppression } from './library/confirm.js';
import { renderAllAnimes } from './library/render.js';
import { ouvrirSante } from './library/sante.js';

function _debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

let _libLoadedAt = 0;
let _libSale     = false;
let _sortActif   = '';
let _langueActif = '';
let _typeActif   = '';
let _recherche   = '';
let _vueMode     = localStorage.getItem('lib_vue') || 'list';
let _favoris     = [];
let _listesUnion = [];
let _listeActive = '';
let _playlist    = [];
let _playlistIdx = 0;

// Trier par nom, par taille ou par episodes prenait deux puces chacun, dont une
// seule servait a la fois : six boutons pour cinq criteres. Un bouton par
// critere qui bascule son sens, et dont l'etiquette porte la fleche du tri
// courant — le sens se lit au lieu de se deviner.
//
// L'etiquette suit toujours `data-sort`, qui vaut le tri applique quand le
// bouton est actif et le tri qu'un clic appliquerait sinon. Rebasculer le
// bouton deja actif inverse le sens ; revenir dessus depuis un autre critere
// retrouve le sens ou on l'avait laisse.
const LIBELLES_TRI = {
  '':    'Défaut',
  fav:   '⭐',
  az:    'A→Z',
  za:    'Z→A',
  size:  'Taille ↓',
  size_asc: 'Taille ↑',
  eps:   'Éps ↓',
  eps_asc:  'Éps ↑',
};

const TRIS = [
  { cle: '' },
  { cle: 'fav', aria: 'Trier par favoris' },
  { sens: ['az', 'za'] },
  { sens: ['size', 'size_asc'] },
  { sens: ['eps', 'eps_asc'] },
];

function _rendreBoutonsTri() {
  return TRIS.map(t => {
    const paire  = t.sens || [];
    const actif  = paire.length ? paire.includes(_sortActif) : t.cle === _sortActif;
    const valeur = paire.length ? (actif ? _sortActif : paire[0]) : t.cle;
    return `<button class="lib-sort-btn${actif ? ' active' : ''}" data-sort="${valeur}"`
      + `${paire.length ? ` data-sens="${paire.join('|')}"` : ''}`
      + `${t.aria ? ` aria-label="${t.aria}"` : ''}`
      + ` aria-pressed="${actif}">${LIBELLES_TRI[valeur]}</button>`;
  }).join('');
}

// Repeindre les puces sur place : reconstruire la barre couperait le geste
// suivant et ferait sauter le defilement, ce que les tests e2e interdisent.
function _majBoutonsTri() {
  document.querySelectorAll('.lib-sort-btn').forEach(btn => {
    const paire = (btn.dataset.sens || '').split('|').filter(Boolean);
    const actif = paire.length ? paire.includes(_sortActif) : (btn.dataset.sort || '') === _sortActif;
    if (actif && paire.length) btn.dataset.sort = _sortActif;
    btn.classList.toggle('active', actif);
    btn.setAttribute('aria-pressed', String(actif));
    const libelle = LIBELLES_TRI[btn.dataset.sort || ''];
    if (libelle) btn.textContent = libelle;
  });
}

// data-nom porte deja le nom normalise avec ses espaces ; cleAnime, la cle de
// rapprochement avec le site, c'est le meme texte sans les espaces. Le
// derivant ici, on evite un attribut de plus sur chaque carte.
function _nomsDeLaListe(id) {
  const noms = new Set();
  if (!id) return noms;
  for (const a of _listesUnion) {
    if (listesDe(a).includes(id)) noms.add(_normalise(a.nom));
  }
  return noms;
}

// Ne proposer que ce qui filtrerait vraiment : une seule liste sur le compte,
// et les puces n'apparaissent pas.
function _listesPresentesLib() {
  return listesPresentes(_listesUnion);
}

// La veille du serveur vient de verifier : la page ouverte reprend son verdict
// (deja en cache cote serveur) au lieu d'afficher l'ancien.
window.addEventListener('nouveautes', () => {
  if (document.getElementById('page-librairie')?.classList.contains('active')) {
    checkNouveauxEpisodes(false);
  }
});

export async function loadLibrairie(force, options = {}) {
  const forceReload = force === true;
  const vivant = options.vivant === true;
  const el     = document.getElementById('lib-content');
  const statEl = document.getElementById('stat-lib');
  if (!el) return;

  // Les 30 s amortissent les allers-retours entre pages. Une invalidation
  // explicite — fin de telechargement, suppression, changement de dossier —
  // doit passer devant : sinon « toujours a jour » attend la fin du minuteur.
  if (!forceReload && !_libSale && state.allAnimes.length
      && (Date.now() - _libLoadedAt) < 30000
      && document.getElementById('lib-anime-list')) {
    return;
  }
  _libSale = false;
  _vueLib.marquerPropre();

  // Reposer le squelette par-dessus une liste deja affichee ferait clignoter
  // la page a chaque episode termine.
  if (!document.getElementById('lib-anime-list')) _renderSkeleton(el);

  try {
    const [libR, favR] = await Promise.allSettled([
      api.getCached('/api/anime/librairie', 30000),
      api.getFavoris(),
    ]);

    const { animes = [], total = 0, tronque = false } = libR.status === 'fulfilled' ? libR.value : {};
    state.allAnimes = animes;
    // « Favoris téléchargés N/M » compte les favoris, pas l'union des listes
    // du compte que /api/anime/favoris renvoie depuis C12.
    _listesUnion = favR.status === 'fulfilled' ? (favR.value.animes || []) : [];
    _favoris   = filtrerListe(_listesUnion, LISTE_DEFAUT);

    if (statEl) _animateStat(statEl, total);

    if (!total) {
      el.innerHTML = `<div class="empty-state"><span class="empty-icon">📭</span><span>Aucun anime téléchargé</span></div>`;
      return;
    }

    try {
      state.covers = await api.getCached('/api/anime/covers', 60000) || {};
      if (!Object.keys(state.covers).length && _favoris.length) {
        _favoris.forEach(a => { if (a.image) state.covers[a.nom] = a.image; });
        if (Object.keys(state.covers).length) {
          api.post('/api/anime/covers', { covers: state.covers }).catch(() => {});
          api.invalidateCache('/api/anime/covers');
        }
      }
    } catch {}

    let totalEps = 0;
    let nbChapitres = 0;
    let totalSizeGB = 0;
    let nbScans = 0;
    let nbAnimes = 0;
    const languesSet = new Set();
    for (const a of animes) {
      totalSizeGB += a.total_size;
      let vid = 0, sc = 0;
      for (const s of a.saisons) {
        for (const e of s.episodes) {
          if (e.scan) { sc++; continue; }
          vid++;
          const lang = detectLangue(e.nom);
          if (lang) languesSet.add(lang);
        }
      }
      totalEps    += vid;
      nbChapitres += sc;
      if (sc)  nbScans++;
      if (vid) nbAnimes++;
    }
    const totalMins = totalEps * 24;
    const langues   = [...languesSet].sort();

    const favSet  = _getFavs();
    const libNoms = new Set(animes.map(a => _normalise(a.nom)));
    const nbFavDl = _favoris.filter(f => libNoms.has(_normalise(f.nom))).length;
    const pctFav  = _favoris.length > 0 ? Math.round(nbFavDl / _favoris.length * 100) : 0;

    el.innerHTML = `
      ${tronque ? `
      <div class="lib-tronquee" role="status">
        ⚠️ Le scan s'est arrêté avant la fin : ta bibliothèque dépasse le plafond
        du serveur. Les chiffres ci-dessous ne comptent que les animes listés.
      </div>` : ''}
      <div class="lib-stats-bar">
        <div class="lib-stat"><span class="lib-stat-icon">📺</span><span class="lib-stat-val" id="lstat-animes">0</span><span class="lib-stat-lbl">Anime${nbAnimes>1?'s':''}</span></div>
        <div class="lib-stat"><span class="lib-stat-icon">🎬</span><span class="lib-stat-val" id="lstat-eps">0</span><span class="lib-stat-lbl">Épisodes</span></div>
        ${nbScans ? `<div class="lib-stat"><span class="lib-stat-icon">📖</span><span class="lib-stat-val lib-txt-rem" id="lstat-scans">0</span><span class="lib-stat-lbl">Scan${nbScans>1?'s':''}</span></div>` : ''}
        ${nbChapitres ? `<div class="lib-stat"><span class="lib-stat-icon">📄</span><span class="lib-stat-val lib-txt-rem" id="lstat-chap">0</span><span class="lib-stat-lbl">Chapitres</span></div>` : ''}
        <div class="lib-stat"><span class="lib-stat-icon">⏱</span><span class="lib-stat-val lib-txt-rem2">${_fmtDuree(totalMins)}</span><span class="lib-stat-lbl">Durée est.</span></div>
        <div class="lib-stat"><span class="lib-stat-icon">💾</span><span class="lib-stat-val" data-s="-webkit-text-fill-color:${totalSizeGB>20?'var(--red)':totalSizeGB>5?'var(--amber)':'var(--green)'};color:${totalSizeGB>20?'var(--red)':totalSizeGB>5?'var(--amber)':'var(--green)'}">${totalSizeGB.toFixed(1)} GB</span><span class="lib-stat-lbl">Stockage</span></div>
        <div class="lib-stat" id="lstat-ep-manquants"></div>
        <div class="lib-stat" id="lstat-nouveaux"></div>
      </div>

      ${_favoris.length ? `
      <div class="lib-progress-wrap">
        <div class="lib-entete">
          <span class="lib-sous-titre">Favoris téléchargés</span>
          <span class="lib-badge-rem2-12">${nbFavDl} / ${_favoris.length} · ${pctFav}%</span>
        </div>
        <div class="progress-bar lib-barre-6">
          <div class="progress-fill lib-barre-remplissage" id="lib-fav-fill"></div>
        </div>
      </div>` : ''}

      <div class="lib-toolbar">
        <div class="lib-search-wrap">
          <input type="text" class="lib-search-input" id="lib-search" value="${esc(_recherche)}" placeholder="🔍 Filtrer par anime ou épisode (ex: E03)…"/>
          <button type="button" id="lib-search-clear" class="lib-search-clear${_recherche ? '' : ' hidden'}" aria-label="Effacer la recherche">×</button>
        </div>
        <div class="lib-toolbar-right">
          ${langues.length > 1 ? `<div class="lib-lang-btns" role="group" aria-label="Langue">
            ${['', ...langues].map(l =>
              `<button class="lib-lang-btn${_langueActif === l ? ' active' : ''}" data-langue="${l}" aria-pressed="${_langueActif === l}">${l || 'Tout'}</button>`).join('')}
          </div>` : ''}
          ${_listesPresentesLib().length ? `<div class="lib-sort-btns lib-mr-4" role="group" aria-label="Listes du compte">
            <button class="lib-expand-btn lib-liste-btn${_listeActive === '' ? ' active' : ''}" data-liste="">Toutes</button>
            ${_listesPresentesLib().map(l =>
              `<button class="lib-expand-btn lib-liste-btn${_listeActive === l.id ? ' active' : ''}" data-liste="${esc(l.id)}" aria-pressed="${_listeActive === l.id}">${esc(l.label)}</button>`).join('')}
          </div>` : ''}
          <div class="lib-sort-btns lib-mr-4" role="group" aria-label="Type de contenu">
            ${[['', 'Tout'], ['anime', '🎬 Animés'], ['scan', '📖 Scans']].map(([v, lbl]) =>
              `<button class="lib-expand-btn lib-type-btn${_typeActif === v ? ' active' : ''}" data-type="${v}" aria-pressed="${_typeActif === v}">${lbl}</button>`).join('')}
          </div>
          <div class="lib-sort-btns" role="group" aria-label="Tri">${_rendreBoutonsTri()}</div>
          <button class="lib-expand-btn" id="lib-expand-all">⊞ Tout ouvrir</button>
          <button class="lib-expand-btn" id="lib-filter-incomplets">⚠️ Incomplets</button>
          <button class="lib-expand-btn" id="lib-check-updates" title="Vérifier les nouveaux épisodes en ligne">🆕 Nouveautés</button>
          <button class="lib-expand-btn" id="lib-coherence" title="Détecter les épisodes en trop (comparaison AniList)">🔎 Cohérence</button>
          <button class="lib-expand-btn" id="lib-sante" title="Fichiers illisibles, tronqués ou restes de téléchargement">🩺 Santé</button>
          <button class="lib-expand-btn" id="lib-vue-toggle">${_vueMode === 'netflix' ? '☰ Liste' : '🎬 Netflix'}</button>
          <button class="lib-expand-btn" id="lib-refresh-toolbar" title="Rafraîchir" aria-label="Rafraîchir la librairie">🔄</button>
        </div>
      </div>
      <div class="lib-ep-counter hidden" id="lib-ep-counter"></div>
      <div id="lib-anime-list" class="${_vueMode === 'netflix' ? 'lib-netflix-grid' : ''}">${renderAllAnimes(animes.slice(0, _LIB_FIRST_CHUNK), favSet)}</div>`;

    _libLoadedAt = Date.now();
    _animateStat(document.getElementById('lstat-animes'), nbAnimes);
    _animateStat(document.getElementById('lstat-eps'), totalEps);
    _animateStat(document.getElementById('lstat-scans'), nbScans);
    _animateStat(document.getElementById('lstat-chap'), nbChapitres);
    bindLibEvents();
    _revealLibCards();

    _renderLibChunks(animes, favSet, () => {
      _revealLibCards();
      detectMissingEps(animes);
      if (Object.keys(state.updatesParAnime).length) {
        injectUpdateBadges();
        majStatNouveaux();
      }
      const fill = document.getElementById('lib-fav-fill');
      if (fill) fill.style.width = pctFav + '%';
      if (animes.length === 1) document.querySelector('.lib-anime')?.classList.add('open');
      _getOpen().forEach(nom => document.getElementById(`lib-${slugify(nom)}`)?.classList.add('open'));
      try { applySortAndFilter(); } catch {}
      // check-updates interroge le site pour chaque anime de la librairie, et
      // le serveur invalide son cache a chaque episode reussi : le relancer sur
      // un rafraichissement vivant lancerait une rafale de requetes distantes a
      // chaque fin d'episode. On rejoue donc ce qu'on sait deja, et l'age
      // affiche dit depuis quand on le sait.
      if (vivant && state.updatesCheckedAt) majStatNouveaux();
      else setTimeout(() => checkNouveauxEpisodes(false), 300);
    });

  } catch(e) {
    el.innerHTML = `<div class="empty-state"><span>❌ ${esc(e.message)}</span></div>`;
    toast(`Erreur librairie : ${e.message}`, 'error');
  }
}

const _LIB_FIRST_CHUNK = 20;
const _LIB_CHUNK = 40;

// Un episode termine, un fichier supprime ou un changement de dossier de
// telechargement changent ce que cette page montre : elle se redessine seule si
// elle est devant l'utilisateur, sinon au retour.
const _vueLib = abonnerVue({
  page: 'librairie',
  sujets: [SUJET_LIBRAIRIE, SUJET_REGLAGES],
  rafraichir: () => loadLibrairie(true, { vivant: true }),
});

// Une suppression faite ici doit aussi corriger les favoris et l'accueil, qui
// affichent « deja telecharge » a partir du meme scan.
function _signalerSuppression() {
  api.invalidateCache('/api/anime/librairie');
  _libSale = true;
  signalerChangement(SUJET_LIBRAIRIE, { origine: 'librairie' });
}

function _revealLibCards() {
  requestAnimationFrame(() => {
    document.querySelectorAll('.lib-anime:not(.visible)').forEach((el, i) => {
      if (i < 12) setTimeout(() => el.classList.add('visible'), i * 30);
      else el.classList.add('visible');
    });
  });
}

function _libFilterActive() {
  return !!((document.getElementById('lib-search')?.value || '').trim())
    || _sortActif !== '' || _langueActif !== '' || _typeActif !== '' || _listeActive !== '';
}

function _renderLibChunks(animes, favSet, onDone) {
  const listEl = document.getElementById('lib-anime-list');
  if (!listEl || animes.length <= _LIB_FIRST_CHUNK) { onDone(); return; }
  let i = _LIB_FIRST_CHUNK;
  const schedule = window.requestIdleCallback
    ? (cb) => window.requestIdleCallback(cb, { timeout: 200 })
    : (cb) => setTimeout(cb, 16);
  const step = () => {
    if (document.getElementById('lib-anime-list') !== listEl) return;
    listEl.insertAdjacentHTML('beforeend', renderAllAnimes(animes.slice(i, i + _LIB_CHUNK), favSet));
    i += _LIB_CHUNK;
    if (_libFilterActive()) applySortAndFilter();
    if (i < animes.length) schedule(step);
    else onDone();
  };
  schedule(step);
}

window._libToggleOpen = (nom) => {
  if (_vueMode === 'netflix') {
    openNetflixModal(nom);
    return;
  }
  const el = document.getElementById(`lib-${slugify(nom)}`);
  const open = el?.classList.toggle('open');
  const openSet = _getOpen();
  if (open) {
    _rattraperFiltreCarte(el);
    openSet.add(nom);
    setTimeout(() => el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 350);
  } else {
    openSet.delete(nom);
  }
  _saveOpen(openSet);
};

function bindLibEvents() {
  const searchInput  = document.getElementById('lib-search');
  const searchClear  = document.getElementById('lib-search-clear');
  const expandAllBtn = document.getElementById('lib-expand-all');
  const refreshBtn   = document.getElementById('lib-refresh-toolbar');
  const vueToggleBtn = document.getElementById('lib-vue-toggle');
  let expandedAll    = false;

  if (_vueMode === 'netflix') {
    document.getElementById('lib-expand-all')?.style && (document.getElementById('lib-expand-all').style.display = 'none');
  }

  // Hors du debounce : un rafraichissement vivant qui tomberait dans les
  // 150 ms rejouerait un champ vide et effacerait la frappe en cours.
  const _appliquerRecherche = _debounce(() => {
    _updateEpCounter();
    applySortAndFilter();
  }, 150);
  searchInput?.addEventListener('input', () => {
    _recherche = searchInput.value;
    searchClear?.classList.toggle('hidden', !_recherche);
    _appliquerRecherche();
  });

  searchClear?.addEventListener('click', () => {
    searchInput.value = '';
    _recherche = '';
    searchClear.classList.add('hidden');
    document.getElementById('lib-ep-counter')?.classList.add('hidden');
    applySortAndFilter();
    searchInput.focus();
  });

  refreshBtn?.addEventListener('click', () => loadLibrairie(true));

  document.getElementById('lib-check-updates')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    const txt = btn.textContent;
    btn.innerHTML = `<span class="spinner lib-ico-11"></span> Vérification…`;
    await checkNouveauxEpisodes(true);
    btn.disabled = false;
    btn.textContent = txt;

    if (Object.keys(state.updatesParAnime).length) {
      showUpdatesModal();
    }
  });

  document.getElementById('lib-sante')?.addEventListener('click', () => {
    ouvrirSante(() => loadLibrairie(true));
  });

  document.getElementById('lib-coherence')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    const txt = btn.textContent;
    btn.innerHTML = `<span class="spinner lib-ico-11"></span> Analyse…`;
    try {
      const r = await api.coherenceLibrairie();
      const inc = r.incoherents || [];
      if (!inc.length) {
        toast(`✅ Aucun excédent détecté en saison 1 — ${r.matched}/${r.total} animes reconnus (AniList)`, 'success', 5000);
      } else {
        const liste = inc.map(x => `${x.nom} : ${x.local} → ${x.canon}`).join('\n');
        toast(`⚠️ ${inc.length} anime(s) avec épisodes possiblement en trop (saison 1, à vérifier — rien n'est supprimé) :\n${liste}`, 'warning', 12000);
      }
    } catch (err) {
      toast(`Erreur cohérence : ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = txt;
    }
  });

  document.getElementById('lib-anime-list')?.addEventListener('click', (e) => {
    const badge = e.target.closest('.lib-new-badge');
    if (!badge) return;
    e.preventDefault();
    e.stopPropagation();
    const nom = badge.dataset.nom;
    if (nom) telechargerNouveauxEpisodes(nom, badge);
  });

  document.getElementById('lib-anime-list')?.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const card = e.target.closest('.lib-header-left[role="button"]');
    if (card && e.target === card) { e.preventDefault(); card.click(); }
  });

  document.getElementById('lib-anime-list')?.addEventListener('dblclick', (e) => {
    const ep = e.target.closest('.lib-ep');
    if (ep) ep.querySelector('[data-action=play], [data-action=read-scan]')?.click();
  });

  vueToggleBtn?.addEventListener('click', () => {
    _vueMode = _vueMode === 'netflix' ? 'list' : 'netflix';
    localStorage.setItem('lib_vue', _vueMode);
    const listEl = document.getElementById('lib-anime-list');
    if (listEl) listEl.className = _vueMode === 'netflix' ? 'lib-netflix-grid' : '';
    vueToggleBtn.textContent = _vueMode === 'netflix' ? '☰ Liste' : '🎬 Netflix';

    const expandBtn = document.getElementById('lib-expand-all');
    if (expandBtn) expandBtn.style.display = _vueMode === 'netflix' ? 'none' : '';
  });

  expandAllBtn?.addEventListener('click', () => {
    if (_vueMode === 'netflix') return;
    expandedAll = !expandedAll;
    document.querySelectorAll('.lib-anime').forEach(el => {
      el.classList.toggle('open', expandedAll);
      _rattraperFiltreCarte(el);
    });
    expandAllBtn.textContent = expandedAll ? '⊟ Tout fermer' : '⊞ Tout ouvrir';
  });

  document.querySelectorAll('.lib-saison-check-wrap[data-stop]').forEach(el => {
    el.addEventListener('click', (e) => e.stopPropagation());
  });

  document.querySelectorAll('.lib-sort-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const paire = (btn.dataset.sens || '').split('|').filter(Boolean);
      _sortActif = paire.includes(_sortActif)
        ? (paire[0] === _sortActif ? paire[1] : paire[0])
        : (btn.dataset.sort || '');
      _majBoutonsTri();
      applySortAndFilter();
    });
  });

  // Les trois barres de filtres partagent le meme geste : re-cliquer la puce
  // active revient a l'ensemble. Une classe et non un style ecrit a la main :
  // le gabarit doit pouvoir rejouer cet etat quand la barre est reconstruite.
  const langBtns = document.querySelectorAll('.lib-lang-btn');
  langBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      _langueActif = basculerFiltre(langBtns, btn, _langueActif, 'langue');
      _updateEpCounter();
      applySortAndFilter();
    });
  });

  const listeBtns = document.querySelectorAll('.lib-liste-btn');
  listeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      _listeActive = basculerFiltre(listeBtns, btn, _listeActive, 'liste');
      applySortAndFilter();
    });
  });

  const typeBtns = document.querySelectorAll('.lib-type-btn');
  typeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      _typeActif = basculerFiltre(typeBtns, btn, _typeActif, 'type');
      applySortAndFilter();
    });
  });

  let incompletFilter = false;
  document.getElementById('lib-filter-incomplets')?.addEventListener('click', function() {
    incompletFilter = !incompletFilter;
    this.style.background   = incompletFilter ? 'rgba(255,200,0,.15)' : '';
    this.style.borderColor  = incompletFilter ? 'var(--yellow)' : '';
    this.style.color        = incompletFilter ? 'var(--yellow)' : '';
    document.querySelectorAll('.lib-anime').forEach(el => {
      if (!incompletFilter) { el.style.display = ''; return; }
      el.style.display = (el.querySelector('.lib-missing-badge') || el.querySelector('.lib-missing-header')) ? '' : 'none';
    });
  });

  document.getElementById('lib-anime-list')?.addEventListener('change', e => {
    const chk   = e.target;
    const anime = chk.closest('.lib-anime');
    if (!anime) return;

    if (chk.classList.contains('lib-saison-check')) {
      const saison = chk.closest('.lib-saison');
      saison?.querySelectorAll('.lib-ep-check:not([data-saison])').forEach(c => { c.checked = chk.checked; });
    }

    const bulkBar = anime.querySelector('.lib-bulk-bar');
    if (!bulkBar) return;
    const checked = anime.querySelectorAll('.lib-ep-check:not([data-saison]):checked');
    if (checked.length) {
      bulkBar.classList.remove('hidden');
      const totalMb = [...checked].reduce((s, chk) => {
        const ep = chk.closest('.lib-ep');
        const txt = ep?.querySelector('div > div:nth-child(2)')?.textContent || '';
        const m = txt.match(/([\d.]+)\s*(MB|GB)/);
        const mb = m ? (m[2] === 'GB' ? parseFloat(m[1]) * 1024 : parseFloat(m[1])) : 0;
        return s + mb;
      }, 0);
      const tailleStr = totalMb >= 1000 ? (totalMb/1024).toFixed(2)+' GB' : totalMb.toFixed(0)+' MB';
      bulkBar.querySelector('.bulk-count').textContent = `${checked.length} sélectionné(s) · ${tailleStr}`;
    } else {
      bulkBar.classList.add('hidden');
    }
  });

  document.getElementById('lib-anime-list')?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;

    if (action === 'toggle-open') {
      window._libToggleOpen(btn.dataset.nom);
      return;
    }

    if (action === 'toggle-fav') {
      const nom    = btn.dataset.nom;
      const favSet = _getFavs();
      if (favSet.has(nom)) favSet.delete(nom);
      else favSet.add(nom);
      _saveFavs(favSet);
      btn.classList.toggle('active', favSet.has(nom));
      const card = document.getElementById(`lib-${slugify(nom)}`);
      card?.classList.toggle('lib-fav-anime', favSet.has(nom));
      card?.setAttribute('data-fav', favSet.has(nom) ? '1' : '0');
      return;
    }

    if (action === 'open-folder-root') {
      const nom   = btn.dataset.nom;
      const anime = state.allAnimes.find(a => a.nom === nom);
      const ep    = anime?.saisons[0]?.episodes[0];

      if (ep) await window.ouvrirDossier(ep.fichier.split(/[/\\]/g).slice(0, -1).join('/'));
      return;
    }

    if (action === 'bulk-delete') {
      const anime   = btn.closest('.lib-anime');
      const checked = [...anime.querySelectorAll('.lib-ep-check:not([data-saison]):checked')];
      if (!checked.length) return;
      if (btn.dataset.confirm !== '1') {
        btn.dataset.confirm = '1';
        btn.textContent = `⚠️ Confirmer (${checked.length} ep)`;
        setTimeout(() => { btn.dataset.confirm = ''; btn.textContent = '🗑 Supprimer la sélection'; }, 4000);
        return;
      }
      let ok = 0;
      for (const chk of checked) {
        const ep      = chk.closest('.lib-ep');
        const fichier = ep?.dataset.fichier?.replace(/\\\\/g, '\\');
        if (!fichier) continue;
        const r = await api.post('/api/anime/supprimer', { fichier }).catch(() => ({ ok: false }));
        if (r.ok) { ep.style.opacity = '0'; setTimeout(() => ep.remove(), 300); ok++; }
      }
      toast(`🗑 ${ok} épisode(s) supprimé(s)`, 'info');
      anime.querySelector('.lib-bulk-bar')?.classList.add('hidden');
      if (ok) _signalerSuppression();
      return;
    }

    if (action === 'bulk-cancel') {
      const anime = btn.closest('.lib-anime');
      anime.querySelectorAll('.lib-ep-check:checked').forEach(c => { c.checked = false; });
      anime.querySelector('.lib-bulk-bar')?.classList.add('hidden');
      return;
    }

    const ep      = btn.closest('.lib-ep');
    const fichier = ep?.dataset.fichier?.replace(/\\\\/g, '\\');
    if (!fichier) return;

    if (action === 'read-scan') {
      const { openLocalReader } = await import('./scan-reader.js');
      const a = state.allAnimes.find(x => x.saisons.some(s => s.episodes.some(e => e.fichier === fichier)));
      const sib = a ? a.saisons.flatMap(s => s.episodes).filter(e => e.scan).map(e => ({ fichier: e.fichier, nom: e.nom })) : null;
      openLocalReader(fichier, ep.querySelector('.lib-ep-nom')?.textContent || 'Scan', sib);
      return;
    }

    if (action === 'play') {
      const anime    = ep.closest('.lib-anime');
      const allEps   = [...(anime?.querySelectorAll('.lib-ep') || [])];
      _playlist    = allEps.map(e => e.dataset.fichier?.replace(/\\\\/g, '\\'));
      _playlistIdx = allEps.indexOf(ep);
      window.lireEpisode(fichier, _playlist, _playlistIdx);
      return;
    }
    if (action === 'copy-path') {
      navigator.clipboard?.writeText(fichier).then(() => {
        toast('📋 Chemin copié !', 'success');
        const orig = btn.textContent;
        btn.textContent = '✅';
        btn.style.color = 'var(--green)';
        setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 1200);
      }).catch(() => toast('❌ Impossible de copier', 'error'));
      return;
    }
    if (action === 'rename') {
      const nomEl  = ep.querySelector('.lib-ep-nom');
      const ancien = nomEl?.textContent || '';
      const nouveau = prompt('Nouveau nom :', ancien);
      if (nouveau && nouveau !== ancien) {
        const names = _getNames();
        names[fichier] = nouveau;
        localStorage.setItem(NAMES_KEY, JSON.stringify(names));
        _invaliderIndexEpisodes();
        ep.dataset.cle = normaliserTexte(nouveau);
        if (nomEl) nomEl.textContent = nouveau;
        toast('✏️ Renommé', 'success');
      }
      return;
    }
    if (action === 'open') { await window.ouvrirDossier(fichier); return; }
    if (action === 'delete') {
      if (confirmSuppression(btn)) {
        const r = await api.post('/api/anime/supprimer', { fichier }).catch(() => ({ ok: false }));
        if (r.ok) {
          ep.style.transition = 'opacity .3s, transform .3s';
          ep.style.opacity = '0'; ep.style.transform = 'translateX(-10px)';
          setTimeout(() => ep.remove(), 300);
          toast('🗑 Épisode supprimé', 'info');
          _signalerSuppression();
        } else toast('❌ Impossible de supprimer', 'error');
      }
    }
  });

  document.removeEventListener('keydown', _libKeyHandler);
  document.addEventListener('keydown', _libKeyHandler);
}

function _libKeyHandler(e) {

  if (!document.getElementById('page-librairie')?.classList.contains('active')) return;
  if (['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)) return;
  if (e.key === 'l' || e.key === 'L') {

    let cible = null;
    const sousSouris = document.elementFromPoint(_libMouseX, _libMouseY);
    if (sousSouris) cible = sousSouris.closest('.lib-anime');

    if (!cible) cible = document.querySelector('.lib-anime');
    if (!cible) return;

    cible.classList.toggle('open');
    _rattraperFiltreCarte(cible);
    const titreEl = cible.querySelector('.lib-anime-title, .lib-title, .lib-header-title');
    const nomReel = (titreEl?.textContent || '').trim();
    const openSet = _getOpen();
    if (nomReel) {
      if (cible.classList.contains('open')) openSet.add(nomReel);
      else                                   openSet.delete(nomReel);
      _saveOpen(openSet);
    }
  }
}

let _libMouseX = 0, _libMouseY = 0;
document.addEventListener('mousemove', (e) => {
  _libMouseX = e.clientX;
  _libMouseY = e.clientY;
}, { passive: true });

function _updateEpCounter() {
  const jetons  = _jetonsCourants();
  const langue  = _langueActif;
  const counter = document.getElementById('lib-ep-counter');
  if (!counter) return;
  if (!jetons.length && !langue) { counter.classList.add('hidden'); return; }

  // On descend depuis les cartes au lieu de remonter par episode : un
  // closest('.lib-anime') par episode, c'etait 5760 remontees d'arbre par
  // frappe pour redecouvrir un nom qu'on connait deja au niveau du dessus.
  let total = 0, visible = 0;
  document.querySelectorAll('.lib-anime').forEach(carte => {
    const animeOk = correspond(carte.dataset.nom || '', jetons);
    carte.querySelectorAll('.lib-ep').forEach(ep => {
      total++;
      const langOk = !langue || ep.dataset.langue === langue;
      const nomOk  = animeOk || correspond(ep.dataset.cle || '', jetons);
      if (langOk && nomOk) visible++;
    });
  });

  counter.textContent = `${visible} épisode${visible>1?'s':''} affiché${visible>1?'s':''} / ${total} total`;
  counter.classList.remove('hidden');
}

// Une librairie fournie depasse 90 000 noeuds : reecrire style.display sur un
// element qui ne change pas suffit a le marquer sale, et le navigateur reprend
// tout le calcul de style. Sur une frappe progressive la plupart des lignes
// gardent leur visibilite — on ne touche que celles qui bougent vraiment.
function _afficher(el, visible) {
  const valeur = visible ? '' : 'none';
  if (el.style.display !== valeur) el.style.display = valeur;
}

// textContent d'un element deja surligne rend le texte nu, <mark> compris :
// il sert donc aussi bien de source pour surligner que de valeur pour effacer.
function _surligner(el, jetons, afficher) {
  const cle = jetons.join(' ');
  if (cle && afficher) {
    if (el.dataset.hlq !== cle) {
      el.innerHTML = highlight(el.textContent, jetons);
      el.dataset.hl = '1';
      el.dataset.hlq = cle;
    }
  } else if (el.dataset.hl === '1') {
    el.textContent = el.textContent;
    el.dataset.hl = '';
    el.dataset.hlq = '';
  }
}

function _jetonsCourants() {
  return jetonsRequete(document.getElementById('lib-search')?.value || '');
}

// Le champ promet « ex: E03 », mais hors filtre langue/type showCard ne
// consultait que le nom de l'anime : une requete ne matchant que des noms
// d'episodes masquait toutes les cartes. Le verdict se prend donc sur les
// donnees — descendre dans les .lib-ep des cartes repliees rendrait le facteur
// 10 gagne sur le filtrage. Memoise par identite du tableau : le chargement
// remplace state.allAnimes, donc un `!==` *est* l'invalidation.
let _indexEps = null;
let _indexEpsSource = null;

function _invaliderIndexEpisodes() {
  _indexEps = null;
  _indexEpsSource = null;
}

function _indexEpisodes() {
  if (_indexEps && _indexEpsSource === state.allAnimes) return _indexEps;
  const noms = _getNames();
  const index = new Map();
  for (const a of state.allAnimes) {
    const parts = [];
    for (const s of a.saisons) {
      for (const e of s.episodes) parts.push(normaliserTexte(noms[e.fichier] || e.nom));
    }
    index.set(normaliserTexte(a.nom), parts.join('\n'));
  }
  _indexEps = index;
  _indexEpsSource = state.allAnimes;
  return index;
}

function _signatureFiltre(jetons) {
  return `${jetons.join(' ')}|${_langueActif}|${_typeActif}`;
}

// Filtrer et surligner les lignes d'episodes d'une carte repliee est du
// travail pur perte : elles sont dans un <details> ferme, dans un .lib-body
// masque. Sur 5760 episodes ca coutait 55 ms d'innerHTML plus autant
// d'ecritures de display — 158 ms par frappe sous Firefox. On ne traite que
// les cartes ouvertes, et la signature dit a l'ouverture s'il faut rattraper.
function _filtrerCarte(carte, jetons) {
  const nom = carte.dataset.nom || '';
  const nomCarteOk = correspond(nom, jetons);
  let hasVisibleEp = false;
  carte.querySelectorAll('.lib-saison').forEach(sais => {
    let saisHasVisible = false;
    sais.querySelectorAll('.lib-ep').forEach(ep => {
      const nomEl  = ep.querySelector('.lib-ep-nom');
      const epScan = ep.dataset.scan === '1';

      const typeEpOk = !_typeActif
        || (_typeActif === 'scan' ? epScan : !epScan);
      const langOk = !_langueActif || ep.dataset.langue === _langueActif;
      // data-cle porte le nom d'episode deja normalise : le replier ici
      // couterait une decomposition Unicode par episode et par frappe.
      const nomOk  = nomCarteOk || correspond(ep.dataset.cle || '', jetons);
      const visible = typeEpOk && langOk && nomOk;
      _afficher(ep, visible);
      if (nomEl) _surligner(nomEl, jetons, visible);
      if (visible) { hasVisibleEp = true; saisHasVisible = true; }
    });
    _afficher(sais, saisHasVisible);
  });
  carte.dataset.filt = _signatureFiltre(jetons);
  return hasVisibleEp;
}

function _rattraperFiltreCarte(carte) {
  if (!carte || !carte.classList.contains('open')) return;
  const jetons = _jetonsCourants();
  if (carte.dataset.filt !== _signatureFiltre(jetons)) _filtrerCarte(carte, jetons);
}

function applySortAndFilter() {
  const jetons = _jetonsCourants();
  const listEl = document.getElementById('lib-anime-list');
  if (!listEl) return;

  let list = [...state.allAnimes];
  if (_sortActif === 'az')       list.sort((a,b) => a.nom.localeCompare(b.nom));
  if (_sortActif === 'za')       list.sort((a,b) => b.nom.localeCompare(a.nom));
  if (_sortActif === 'size')     list.sort((a,b) => b.total_size - a.total_size);
  if (_sortActif === 'size_asc') list.sort((a,b) => a.total_size - b.total_size);
  if (_sortActif === 'eps')      list.sort((a,b) => b.total_eps - a.total_eps);
  if (_sortActif === 'eps_asc')  list.sort((a,b) => a.total_eps - b.total_eps);
  if (_sortActif === 'fav')  {
    const favSet = _getFavs();
    list.sort((a,b) => (favSet.has(b.nom)?1:0) - (favSet.has(a.nom)?1:0));
  }

  if (_sortActif) {
    const refs = {};
    list.forEach(a => {
      const el = document.getElementById(`lib-${slugify(a.nom)}`);
      if (el) refs[a.nom] = el;
    });
    // Vider innerHTML effondre la hauteur du conteneur : le navigateur rabote
    // alors scrollTop a zero, et ne le restaure pas quand les cartes reviennent.
    // C'est la seconde cause du « trier fait remonter la page », a cote de
    // softScrollTop — le retrait de celui-ci seul ne suffisait pas.
    const scroller = document.querySelector('.main');
    const y = scroller ? scroller.scrollTop : 0;
    const frag = document.createDocumentFragment();
    list.forEach(a => { if (refs[a.nom]) frag.appendChild(refs[a.nom]); });
    listEl.replaceChildren(frag);
    if (scroller && scroller.scrollTop !== y) scroller.scrollTop = y;
  }

  const indexEps = jetons.length ? _indexEpisodes() : null;
  const nomsListe = _nomsDeLaListe(_listeActive);

  let _visibleCards = 0;
  document.querySelectorAll('.lib-anime').forEach(el => {
    const nom     = el.dataset.nom || '';
    const nomMatch = correspond(nom, jetons);
    const epMatch  = indexEps ? correspond(indexEps.get(nom) || '', jetons) : false;
    let   hasVisibleEp = false;

    // Un filtre de langue ou de type decide du sort de la carte a partir de
    // ses episodes : la, il faut les parcourir meme repliee.
    if (el.classList.contains('open') || _langueActif || _typeActif) {
      hasVisibleEp = _filtrerCarte(el, jetons);
    } else {
      el.dataset.filt = '';
    }

    const hasScan  = el.dataset.hasScan === '1';
    const hasVideo = el.dataset.hasVideo === '1';
    const typeOk = !_typeActif
      || (_typeActif === 'scan' && hasScan)
      || (_typeActif === 'anime' && hasVideo);

    // Le rapprochement avec le site se fait sur le nom sans espaces, alors que
    // data-nom les conserve : c'est la meme normalisation a l'espace pres.
    const listeOk = !_listeActive || nomsListe.has(nom.replaceAll(' ', ''));

    const showCard =
      ((_langueActif || _typeActif) ? hasVisibleEp : (nomMatch || epMatch)) && typeOk && listeOk;
    _afficher(el, showCard);
    if (showCard) _visibleCards++;

    const scanBadge = el.querySelector('.lib-scan-badge');
    if (scanBadge) _afficher(scanBadge, _typeActif !== 'anime');

    const titleEl = el.querySelector('.lib-title');
    if (titleEl) _surligner(titleEl, jetons, showCard);
  });

  _toggleLibFilterEmpty(listEl, _visibleCards);
}

function _toggleLibFilterEmpty(listEl, visibleCards) {
  let el = document.getElementById('lib-empty-filter');
  const show = visibleCards === 0 && state.allAnimes.length > 0;
  if (!el) {
    if (!show) return;
    el = document.createElement('div');
    el.id = 'lib-empty-filter';
    el.className = 'empty-state';
    el.innerHTML = '<span class="empty-icon" aria-hidden="true">🔍</span><span>Aucun anime ne correspond à ce filtre</span>';
    listEl.parentNode.insertBefore(el, listEl.nextSibling);
  }
  el.classList.toggle('hidden', !show);
}

function _animateStat(el, target) { animateCount(el, target); }

function _renderSkeleton(el) {
  el.innerHTML = Array(5).fill(0).map(() => `
    <div class="lib-anime skeleton-card lib-mb-10">
      <div class="lib-ligne-12">
        <div class="skeleton-img lib-vignette"></div>
        <div class="lib-flex-1">
          <div class="skeleton-line lib-w-55"></div>
          <div class="skeleton-line lib-w-30"></div>
        </div>
      </div>
    </div>`).join('');
}
