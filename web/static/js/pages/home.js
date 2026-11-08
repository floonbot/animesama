import { esc } from '../utils/escape.js';
import { coverSrc } from '../utils/cover.js';
import { api }        from '../api.js';
import { toast }      from '../components/toast.js';
import { navigateTo } from '../router.js';
import { cleAnime as _normaliser } from '../utils/texte.js';
import { episodesRestantsItemCourant, fmtReste, resteAnimeS, resteEpisodeS } from '../utils/eta.js';
import { etiquetteEpisode } from '../utils/etiquette.js';
import { SUJET_LIBRAIRIE, SUJET_REGLAGES, abonnerVue } from '../utils/vue-live.js';
import { LISTE_DEFAUT, filtrerListe } from '../utils/listes.js';

let _sessionCheckInterval = null;
let _clockInterval        = null;
let _statsLoaded          = false;
let _favoris              = [];
const SESSION_KEY = 'anime_session_today';

function _fadeInSections() {
  const sections = [...document.querySelectorAll('#page-home .fade-section')].filter(el => !el.classList.contains('hidden'));
  requestAnimationFrame(() => {
    sections.forEach((el, i) => {
      if (i === 0) el.classList.add('visible');
      else setTimeout(() => el.classList.add('visible'), i * 35);
    });
  });
}

let _sectionObs = null;

function _observeSections() {

  if (_sectionObs) { try { _sectionObs.disconnect(); } catch {} }
  const obs = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.classList.add('visible');
        obs.unobserve(e.target);
      }
    });
  }, { threshold: 0.1 });
  _sectionObs = obs;

  document.querySelectorAll('#page-home .fade-section').forEach(el => {
    if (!el.classList.contains('hidden')) obs.observe(el);
  });
}

function _getSessionData() {
  try {
    const today = new Date().toDateString();
    const raw   = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const data  = JSON.parse(raw);
    return data.date === today ? data : null;
  } catch { return null; }
}

function _updateSessionData(updates) {
  try {
    const today   = new Date().toDateString();
    const current = _getSessionData() || { date: today, succes: 0, echoues: 0, annules: 0, minutes: 0 };
    const merged  = { ...current, ...updates, date: today };
    localStorage.setItem(SESSION_KEY, JSON.stringify(merged));
  } catch {}
}

const RACCOURCIS = [
  {
    titre: '🧭 Général',
    items: [
      { keys: ['/'],     desc: 'Ouvrir / focus la barre de recherche' },
      { keys: ['Échap'], desc: 'Fermer la fenêtre ouverte (fiche anime, lecteur…)' },
    ],
  },
  {
    titre: '⬇️ Téléchargements',
    items: [
      { keys: ['P'],     desc: 'Mettre en pause / reprendre le téléchargement' },
      { keys: ['Échap'], desc: 'Annuler le téléchargement en cours' },
      { keys: ['Glisser'], desc: 'Réorganiser la file (la page défile toute seule)' },
    ],
  },
  {
    titre: '📁 Librairie',
    items: [
      { keys: ['L'], desc: 'Déplier / replier la fiche d\'un anime' },
    ],
  },
  {
    titre: '🎬 Lecteur vidéo',
    items: [
      { keys: ['Espace'],   desc: 'Lecture / pause' },
      { keys: ['F'],        desc: 'Plein écran' },
      { keys: ['M'],        desc: 'Couper / activer le son' },
      { keys: ['N'],        desc: 'Épisode suivant' },
      { keys: ['←', '→'],   desc: 'Reculer / avancer de 5 secondes' },
      { keys: ['↑', '↓'],   desc: 'Augmenter / baisser le volume' },
    ],
  },
];

const QUOTES = [
  { text: 'Je reviendrai à toi, peu importe combien de fois il le faudra.', author: 'Subaru — Re:Zero' },
  { text: 'Les rêves ne se réalisent pas. Tu dois te lever et les réaliser toi-même.', author: 'Rock Lee — Naruto' },
  { text: 'L\'ignorance est une bénédiction — mais seulement si tu ne peux rien y changer.', author: 'Alucard — Hellsing' },
  { text: 'Si tu n\'aimes pas ce que tu es, change-le — tu en as le pouvoir.', author: 'Saitama — One Punch Man' },
  { text: 'Un héros peut être n\'importe qui, même quelqu\'un qui fait une seule chose bien.', author: 'Izuku Midoriya — MHA' },
  { text: 'Ne mourez pas avant d\'avoir vu vos rêves se réaliser.', author: 'Gintoki — Gintama' },
  { text: 'L\'enfer n\'est pas un endroit — c\'est un état d\'esprit.', author: 'L — Death Note' },
  { text: 'Le passé ne change pas — mais comment tu le regardes, oui.', author: 'Edward Elric — FMA' },
  { text: 'Peu importe la difficulté, peu importe l\'impossibilité — ne perds jamais espoir.', author: 'Monkey D. Luffy — One Piece' },
  { text: 'Si tu veux pleurer, pleure. Tu te sentiras mieux après.', author: 'Nezuko — Demon Slayer' },
  { text: 'Le monde est cruel, mais aussi terriblement beau.', author: 'Mikasa — L\'Attaque des Titans' },
  { text: 'Une leçon sans douleur n\'a aucun sens. On ne peut rien gagner sans rien sacrifier.', author: 'Edward Elric — FMA' },
  { text: 'Ce ne sont pas tes capacités qui montrent qui tu es, mais tes choix.', author: 'Dumbledore… non, Itachi — Naruto' },
  { text: 'Tant que tu n\'abandonnes pas, il y a toujours une chance.', author: 'Tanjiro — Demon Slayer' },
  { text: 'Les gens vivent vraiment quand ils sont prêts à mourir pour quelque chose.', author: 'Kamina — Gurren Lagann' },
  { text: 'Crois en le toi qui croit en toi.', author: 'Kamina — Gurren Lagann' },
  { text: 'Ne regrette jamais ce qui t\'a rendu plus fort.', author: 'Erza — Fairy Tail' },
  { text: 'On ne sait jamais à quel point on est fort, jusqu\'à ce qu\'être fort soit le seul choix possible.', author: 'Johnny — Re:Zero' },
  { text: 'La peur n\'est pas le mal. Elle te montre tes faiblesses pour que tu grandisses.', author: 'Gildarts — Fairy Tail' },
  { text: 'Le vrai courage, c\'est de continuer à avancer malgré la peur.', author: 'Asta — Black Clover' },
  { text: 'Un sourire vaut mille mots, surtout quand le cœur est lourd.', author: 'Yuno — Black Clover' },
  { text: 'On ne devient pas un héros en gagnant — mais en se relevant.', author: 'All Might — MHA' },
];

export async function checkAuth() {
  try {
    const r = await api.getAuthStatus();
    _updateUI(r);
  } catch {}
}

function _salutation() {
  const h = new Date().getHours();
  if (h < 6)  return 'Bonne nuit';
  if (h < 12) return 'Bonjour';
  if (h < 18) return 'Bon après-midi';
  return 'Bonsoir';
}

function _lastSeenText() {
  const ts = localStorage.getItem('last_seen');
  if (!ts) { localStorage.setItem('last_seen', Date.now()); return 'Première visite !'; }
  const diff = Math.floor((Date.now() - parseInt(ts)) / 60000);
  localStorage.setItem('last_seen', Date.now());
  if (diff < 2)    return 'À l\'instant';
  if (diff < 60)   return `Il y a ${diff} min`;
  if (diff < 1440) return `Il y a ${Math.floor(diff/60)}h`;
  return `Il y a ${Math.floor(diff/1440)}j`;
}

function _startClock() {
  if (_clockInterval) return;
  const JOURS = ['Dimanche','Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi'];
  const MOIS  = ['jan','fév','mar','avr','mai','juin','juil','aoû','sep','oct','nov','déc'];
  const tick  = () => {
    const now  = new Date();
    const h    = String(now.getHours()).padStart(2,'0');
    const m    = String(now.getMinutes()).padStart(2,'0');
    const s    = String(now.getSeconds()).padStart(2,'0');
    const ck   = document.getElementById('home-clock');
    const dk   = document.getElementById('home-date');
    if (ck) {
      ck.textContent = `${h}:${m}:${s}`;
      if (ck.animate) ck.animate([{ transform: 'scale(1.06)' }, { transform: 'scale(1)' }], { duration: 150, easing: 'ease-out' });
      else { ck.classList.remove('clock-tick'); ck.classList.add('clock-tick'); }
    }
    if (dk) dk.textContent = `${JOURS[now.getDay()]} ${now.getDate()} ${MOIS[now.getMonth()]}`;
  };
  tick();
  _clockInterval = setInterval(tick, 1000);
}

function _showQuote(animate = false) {
  const wrap   = document.getElementById('hero-quote');
  const textEl = document.getElementById('hero-quote-text');
  const authEl = document.getElementById('hero-quote-author');
  if (!wrap || !textEl || !authEl) return;
  const idx = Math.floor(Math.random() * QUOTES.length);
  if (animate) {
    wrap.style.opacity = '0';
    setTimeout(() => {
      textEl.textContent = `« ${QUOTES[idx].text} »`;
      authEl.textContent = `— ${QUOTES[idx].author}`;
      wrap.style.transition = 'opacity .5s';
      wrap.style.opacity    = '1';
    }, 300);
  } else {
    textEl.textContent = `« ${QUOTES[idx].text} »`;
    authEl.textContent = `— ${QUOTES[idx].author}`;
    wrap.classList.remove('hidden');
  }
}

let _quoteInterval = null;
function _startQuoteRotation() {
  if (_quoteInterval) return;
  _quoteInterval = setInterval(() => _showQuote(true), 30_000);
}

function _renderRaccourcis() {
  const el = document.getElementById('home-raccourcis-content');
  if (!el) return;
  el.innerHTML = RACCOURCIS.map(groupe => `
    <div class="raccourcis-group">
      <div class="raccourcis-group-title">${groupe.titre}</div>
      <ul class="raccourcis-list">
        ${groupe.items.map(it => `
          <li class="raccourcis-row">
            <span class="raccourcis-keys">
              ${it.keys.map(k => `<kbd class="kbd">${esc(k)}</kbd>`).join('<span class="kbd-sep">/</span>')}
            </span>
            <span class="raccourcis-desc">${esc(it.desc)}</span>
          </li>`).join('')}
      </ul>
    </div>`).join('');
}

function _updateUI(r) {
  const nameEl    = document.getElementById('user-name');
  const statusEl  = document.getElementById('user-status');
  const heroBtn   = document.getElementById('hero-connect');
  const heroSub   = document.querySelector('.hero-sub');
  const dot       = document.getElementById('user-status-dot');
  const logoutBtn = document.getElementById('btn-logout');
  const avatarEl  = document.getElementById('user-avatar');
  const greetEl   = document.getElementById('home-greeting');
  const shortcuts = document.getElementById('home-shortcuts');
  const raccBlock = document.getElementById('home-raccourcis');

  _startClock();

  if (r.connected && r.username) {
    const displayName = r.username.includes('.')
      ? r.username.split('.')[0]
      : r.username;

    if (nameEl)    { nameEl.textContent = displayName; nameEl.title = r.username; }
    if (statusEl)  { statusEl.textContent = `✅ Connecté · ${_lastSeenText()}`; statusEl.style.color = 'var(--green)'; }
    if (dot)       { dot.style.background = 'var(--green)'; dot.title = 'Session active'; }
    if (avatarEl)  avatarEl.textContent  = '🟢';
    if (logoutBtn) logoutBtn.classList.remove('hidden');
    if (greetEl)   greetEl.textContent   = `${_salutation()}, ${displayName} 👋`;
    document.querySelector('.hero')?.classList.add('hero-animated');
    if (shortcuts) shortcuts.classList.remove('hidden');
    if (raccBlock) { raccBlock.classList.remove('hidden'); _renderRaccourcis(); }

    _showQuote();
    _startQuoteRotation();
    requestAnimationFrame(() => {
      document.querySelector('#page-home .hero')?.classList.add('visible');
      document.querySelector('#page-home .stats')?.classList.add('visible');
    });

    if (heroBtn) {
      heroBtn.textContent = '⭐ Mes favoris';
      heroBtn.onclick = () => navigateTo('favoris');
    }
    if (heroSub) heroSub.textContent = 'Tes favoris et épisodes sont prêts à être téléchargés.';

    _updateSettingsSection(r.username, true);
    startSessionWatch();

    if (!_statsLoaded) { _statsLoaded = true; _loadStats(); }
  } else {
    if (nameEl)    nameEl.textContent  = 'Non connecté';
    if (statusEl)  { statusEl.textContent = 'Cliquer pour se connecter'; statusEl.style.color = ''; }
    if (dot)       { dot.style.background = 'var(--red)'; dot.title = 'Non connecté'; }
    if (avatarEl)  avatarEl.textContent  = '👤';
    if (logoutBtn) logoutBtn.classList.add('hidden');
    if (greetEl)   greetEl.textContent   = 'Bienvenue';
    if (shortcuts) shortcuts.classList.add('hidden');
    if (raccBlock) raccBlock.classList.add('hidden');

    document.getElementById('hero-quote')?.classList.add('hidden');
    document.getElementById('home-recent')?.classList.add('hidden');
    document.getElementById('home-anime-du-jour')?.classList.add('hidden');
    document.getElementById('home-session-bilan')?.classList.add('hidden');

    if (heroBtn) { heroBtn.textContent = '⚡ Se connecter'; heroBtn.onclick = null; }

    ['stat-dl','stat-fav','stat-lib'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = '—';
    });

    _updateSettingsSection('', false);
    stopSessionWatch();
    _stopClock();
    _stopQuoteRotation();
    _statsLoaded = false;
    _favoris = [];
    _statsSeq++;
  }
}

let _statsSeq = 0;

// _statsLoaded ne laissait charger les compteurs qu'une fois par session : un
// episode telecharge ne bougeait ni « Librairie » ni « Téléchargés » tant que
// l'onglet restait ouvert.
abonnerVue({
  page: 'home',
  sujets: [SUJET_LIBRAIRIE, SUJET_REGLAGES],
  rafraichir: () => { if (_statsLoaded) _loadStats(); },
});

async function _loadStats() {
  const _seq = ++_statsSeq;
  try {
    const [favR, libR, dlR] = await Promise.allSettled([
      api.getFavoris(),
      api.getCached('/api/anime/librairie', 30000),
      api.getDlStatus(),
    ]);

    if (_seq !== _statsSeq) return;

    // La charge utile porte l'union des listes du compte depuis C12 ; tout ce
    // que cette page appelle « favoris » doit le rester.
    const animesFav = filtrerListe(
      favR.status === 'fulfilled' ? (favR.value.animes || []) : [], LISTE_DEFAUT,
    );
    const animesLib = libR.status === 'fulfilled' ? (libR.value.animes || []) : [];
    _favoris = animesFav;

    const nbFav = animesFav.length;
    const nbLib = libR.status === 'fulfilled' ? (libR.value.total || 0) : 0;
    const nbDl  = dlR.status  === 'fulfilled'
      ? (dlR.value.historique?.reduce((s, h) => s + (h.succes || 0), 0) || 0)
      : 0;

    _setStatAnimated('stat-fav', nbFav);
    _setStatAnimated('stat-lib', nbLib);
    _setStatAnimated('stat-dl',  nbDl);

    const scFav = document.getElementById('sc-fav-count');
    const scLib = document.getElementById('sc-lib-count');
    const scDl  = document.getElementById('sc-dl-count');
    if (scFav) scFav.textContent = nbFav ? `${nbFav} anime${nbFav>1?'s':''}` : 'Aucun favori';
    if (scLib) scLib.textContent = nbLib ? `${nbLib} anime${nbLib>1?'s':''}` : 'Librairie vide';
    if (scDl)  scDl.textContent  = nbDl  ? `${nbDl} épisode${nbDl>1?'s':''}` : 'Aucun téléchargé';

    if (animesLib.length) _loadRecent(animesLib);
    if (animesFav.length) {
      _loadAnimeDuJour(animesFav, animesLib);
      _loadBilan(animesFav, animesLib);
    }

    if (dlR.status === 'fulfilled') _loadMeteo(dlR.value);

    setTimeout(() => { _fadeInSections(); _observeSections(); }, 100);

  } catch {}
}

function _loadAnimeDuJour(favoris, librairie) {
  const section = document.getElementById('home-anime-du-jour');
  const content = document.getElementById('anime-du-jour-content');
  if (!section || !content || !favoris.length) return;

  const idx   = Math.floor(Date.now() / 86400000) % favoris.length;
  const anime = favoris[idx];
  const libNoms = new Set(librairie.map(a => _normaliser(a.nom)));
  const deja    = libNoms.has(_normaliser(anime.nom));

  content.innerHTML = `
    ${anime.image
      ? `<img class="anime-du-jour-cover" src="${esc(coverSrc(anime.image))}" alt="${esc(anime.nom)}">`
      : `<div class="anime-du-jour-cover-placeholder">🎌</div>`}
    <div class="anime-du-jour-info">
      <div class="anime-du-jour-label">🎲 Anime du jour</div>
      <div class="anime-du-jour-title">${esc(anime.nom)}</div>
      <div class="anime-du-jour-statut">${esc(anime.statut || '')}${deja ? ' · ✅ Déjà téléchargé' : ''}</div>
    </div>`;

  section.classList.remove('hidden');

}

function _loadBilan(favoris, librairie) {
  const section = document.getElementById('home-session-bilan');
  if (!section) return;

  const libNoms  = new Set(librairie.map(a => _normaliser(a.nom)));
  const nbTotal  = favoris.length;
  const nbDl     = favoris.filter(a => libNoms.has(_normaliser(a.nom))).length;
  const pct      = nbTotal > 0 ? Math.round(nbDl / nbTotal * 100) : 0;

  const ratioEl  = document.getElementById('bilan-ratio');
  const fillEl   = document.getElementById('bilan-fill');
  const pctEl    = document.getElementById('bilan-pct');
  const subEl    = document.getElementById('bilan-sub');

  if (ratioEl) ratioEl.textContent = `${nbDl} / ${nbTotal}`;
  if (pctEl)   pctEl.textContent   = `${pct}%`;
  if (subEl)   subEl.textContent   = nbDl === nbTotal && nbTotal > 0
    ? '🎉 Tous tes favoris sont téléchargés !'
    : `${nbTotal - nbDl} anime${nbTotal-nbDl>1?'s':''} encore à télécharger`;

  if (fillEl) {
    fillEl.style.width = '0%';
    setTimeout(() => { fillEl.style.transition = 'width 1s ease'; fillEl.style.width = pct + '%'; }, 100);
  }

  section.classList.remove('hidden');
}

function _loadMeteo(dlStatus) {
  const section = document.getElementById('home-meteo');
  const grid    = document.getElementById('meteo-grid');
  if (!section || !grid) return;

  const today   = new Date().toDateString();
  const hist    = (dlStatus?.historique || []).filter(h => {
    try { return new Date(h.date || today).toDateString() === today; } catch { return true; }
  });

  const succes  = hist.reduce((s, h) => s + (h.succes  || 0), 0);
  const echoues = hist.reduce((s, h) => s + (h.echoues || 0), 0);
  const annules = hist.filter(h => h.annule).length;

  const session = _getSessionData() || {};
  const minutes = session.minutes || Math.floor((Date.now() - (session.start || Date.now())) / 60000);

  if (!session.start) _updateSessionData({ start: Date.now() });

  const items = [
    { icon: '✅', val: succes,              lbl: 'Téléchargés' },
    { icon: '❌', val: echoues,             lbl: 'Échoués'      },
    { icon: '⛔', val: annules,             lbl: 'Annulés'      },
    { icon: '⏱', val: minutes + ' min',    lbl: 'Durée session' },
  ];

  grid.innerHTML = items.map(it => `
    <div class="meteo-card">
      <span class="meteo-icon">${it.icon}</span>
      <span class="meteo-val">${it.val}</span>
      <span class="meteo-lbl">${it.lbl}</span>
    </div>`).join('');

  section.classList.remove('hidden');
  section.classList.add('fade-section');
}

function _loadRecent(animes) {
  const section = document.getElementById('home-recent');
  const grid    = document.getElementById('home-recent-grid');
  if (!section || !grid || !animes.length) return;

  const animesAvecMtime = animes.map(a => {
    let lastMtime = 0;
    for (const s of (a.saisons || [])) {
      for (const ep of (s.episodes || [])) {
        if (ep.mtime && ep.mtime > lastMtime) lastMtime = ep.mtime;
      }
    }
    return { anime: a, mtime: lastMtime };
  });
  animesAvecMtime.sort((a, b) => b.mtime - a.mtime);
  const animesTries = animesAvecMtime.map(x => x.anime);

  api.getCached('/api/anime/covers', 60000).then(async covers => {
    covers = covers || {};
    if (!Object.keys(covers).length && _favoris.length) {
      _favoris.forEach(a => { if (a.image) covers[a.nom] = a.image; });
    }
    _renderRecent(animesTries, grid, covers);
  }).catch(() => {
    const covers = {};
    _favoris.forEach(a => { if (a.image) covers[a.nom] = a.image; });
    _renderRecent(animesTries, grid, covers);
  });

  section.classList.remove('hidden');
}

function _renderRecent(animes, grid, covers) {
  const recent = animes.slice(0, 3);
  grid.innerHTML = recent.map(a => {
    const cover = covers[a.nom] || '';
    const eps   = a.total_eps || 0;
    const size  = a.total_size ? `${a.total_size} GB` : '';
    return `
      <div class="recent-card" role="button" tabindex="0" aria-label="${esc(a.nom)} — voir dans la librairie">
        ${cover
          ? `<img class="recent-cover" src="${esc(coverSrc(cover))}" alt="${esc(a.nom)}" loading="lazy" decoding="async">`
          : `<div class="recent-cover recent-cover-placeholder" data-s="display:flex;align-items:center;justify-content:center;font-size:20px">🎌</div>`}
        <div class="recent-info">
          <div class="recent-title">${esc(a.nom)}</div>
          <div class="recent-sub">${eps} épisode${eps>1?'s':''}${size ? ` · ${size}` : ''}</div>
        </div>
      </div>`;
  }).join('');

  grid.querySelectorAll('.recent-card').forEach(card => {
    card.addEventListener('click', () => navigateTo('librairie'));
    card.addEventListener('keydown', (e) => {
      if (e.repeat) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        navigateTo('librairie');
      }
    });
  });
}

function _setStatAnimated(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  if (target === 0) { el.textContent = '0'; return; }
  let current = 0;
  const step  = Math.ceil(target / 20);
  const timer = setInterval(() => {
    current = Math.min(current + step, target);
    el.textContent = current;
    if (current >= target) clearInterval(timer);
  }, 40);
}

function _updateSettingsSection(username, connected) {
  const userSection  = document.getElementById('settings-user-section');
  const loginSection = document.getElementById('settings-login-section');
  const usernameEl   = document.getElementById('settings-username');
  // Les deux blocs naissent avec la classe .hidden, qui est en
  // « display:none !important » : ecrire style.display ne pouvait pas la
  // battre, et la carte « Compte » restait vide — ni connexion ni deconnexion
  // depuis les Parametres.
  userSection?.classList.toggle('hidden', !connected);
  loginSection?.classList.toggle('hidden', connected);
  if (usernameEl) usernameEl.textContent = username || '';
}

async function _doLogout() {
  try {
    await api.logout();
    toast('👋 Déconnecté', 'info');
    _updateUI({ connected: false });
  } catch(e) {
    toast(`❌ ${e.message}`, 'error');
  }
}

export function initLogoutButtons() {
  document.getElementById('btn-logout')?.addEventListener('click', _doLogout);
  document.getElementById('settings-logout')?.addEventListener('click', _doLogout);
  document.getElementById('settings-connect')?.addEventListener('click', () => {
    document.getElementById('modal-login')?.classList.remove('hidden');
  });

  const nav = (page) => () => navigateTo(page);
  document.getElementById('stat-card-dl')     ?.addEventListener('click', nav('telechargements'));
  document.getElementById('stat-card-fav')    ?.addEventListener('click', nav('favoris'));
  document.getElementById('stat-card-lib')    ?.addEventListener('click', nav('librairie'));
  document.getElementById('hero-search')      ?.addEventListener('click', nav('recherche'));
  document.getElementById('hero-dl')          ?.addEventListener('click', nav('telechargements'));
  document.getElementById('hero-lib')         ?.addEventListener('click', nav('librairie'));
  document.getElementById('hero-settings-btn')?.addEventListener('click', () => document.getElementById('nav-settings')?.click());
  document.getElementById('hero-diag')        ?.addEventListener('click', nav('diag'));
  document.getElementById('sc-btn-fav')           ?.addEventListener('click', nav('favoris'));
  document.getElementById('sc-btn-search')        ?.addEventListener('click', nav('recherche'));
  document.getElementById('sc-btn-dl')            ?.addEventListener('click', nav('telechargements'));
  document.getElementById('sc-btn-lib')           ?.addEventListener('click', nav('librairie'));
  document.getElementById('sc-btn-diag')          ?.addEventListener('click', nav('diag'));
  document.getElementById('home-dl-voir-tout')    ?.addEventListener('click', nav('telechargements'));
  document.getElementById('home-recent-voir-tout')?.addEventListener('click', nav('librairie'));
}

export function updateHomeDlWidget(state) {
  const widget = document.getElementById('home-dl-widget');
  if (!widget) return;
  if (!state?.en_cours) {
    widget.classList.add('hidden');
    const fill = document.getElementById('home-dl-fill');
    if (fill) fill.style.width = '0%';
    return;
  }
  widget.classList.remove('hidden');
  const titre = state.en_cours.episodes?.[0]?.titre || state.en_cours.nom || '?';
  const ep    = state.en_cours.episodes?.[0];
  const sub   = etiquetteEpisode(ep);
  const titleEl = document.getElementById('home-dl-title');
  const subEl   = document.getElementById('home-dl-sub');
  if (titleEl) titleEl.textContent = titre;
  if (subEl)   subEl.textContent   = sub || (state.en_pause ? '⏸ En pause' : 'En cours…');
}

export function updateHomeDlProgress(pct) {
  const fill  = document.getElementById('home-dl-fill');
  const pctEl = document.getElementById('home-dl-pct');
  if (fill)  fill.style.width  = Math.min(pct, 100) + '%';
  if (pctEl) pctEl.textContent = pct > 0 ? pct.toFixed(0) + '%' : '';
  majHomeEta();
}

// Le meme temps restant que la page Téléchargements, sur la carte de l'accueil :
// rafraichi par le minuteur du flux, il descend sans qu'on change de page.
export function majHomeEta() {
  const el = document.getElementById('home-dl-eta');
  if (!el) return;
  // L'anime entier quand d'autres episodes suivent : c'est la question que la
  // carte de l'accueil doit trancher (« quand aurai-je fini ? »).
  const reste = episodesRestantsItemCourant() > 0 ? resteAnimeS() : resteEpisodeS();
  el.textContent = reste == null ? '' : reste < 1 ? '⏱ finalisation…' : `⏱ ${fmtReste(reste)} restantes`;
}

function startSessionWatch() {
  if (_sessionCheckInterval) return;
  _sessionCheckInterval = setInterval(async () => {
    try {
      const r = await api.getAuthStatus();
      if (!r.connected) {
        stopSessionWatch();
        const statusEl = document.getElementById('user-status');
        const dot      = document.getElementById('user-status-dot');
        if (statusEl) { statusEl.textContent = '⚠️ Session expirée'; statusEl.style.color = 'var(--yellow)'; }
        if (dot)      { dot.style.background = 'var(--yellow)'; dot.title = 'Session expirée'; }
        document.getElementById('btn-logout')?.classList.add('hidden');
        toast('⚠️ Ta session a expiré. Reconnecte-toi.', 'error', 8000);
        _updateSettingsSection('', false);
        _statsLoaded = false;
      }
    } catch {}
  }, 60_000);
}

function stopSessionWatch() {
  if (_sessionCheckInterval) { clearInterval(_sessionCheckInterval); _sessionCheckInterval = null; }
}

function _stopClock() {
  if (_clockInterval) { clearInterval(_clockInterval); _clockInterval = null; }
}

function _stopQuoteRotation() {
  if (_quoteInterval) { clearInterval(_quoteInterval); _quoteInterval = null; }
}
