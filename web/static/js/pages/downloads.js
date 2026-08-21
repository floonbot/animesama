import { esc } from '../utils/escape.js';
import { coverSrc } from '../utils/cover.js';
import { api }   from '../api.js';
import { toast } from '../components/toast.js';
import * as eta from '../utils/eta.js';
import { etiquetteEpisode } from '../utils/etiquette.js';
import { SUJET_REGLAGES } from '../utils/vue-live.js';

const HIST_KEY   = 'dl_historique';
const MAX_HIST   = 30;
let _dragIdx        = null;
let _lastEnCours    = null;
let _lastQueueState = null;
let _covers         = {};

let _coversCacheTs = 0;
let _coversAbort   = null;
const COVERS_CACHE_TTL = 60_000;

let _audioCtx = null;
let _clearHistoryBound = false;

// Lu une seule fois a l'import, ce cache figeait « son de notification » :
// decocher la case n'avait aucun effet avant un rechargement complet de la page.
let _settingsCache = null;
async function _relireReglages() {
  try { _settingsCache = await api.getCached('/api/settings', 30000); } catch {}
}
_relireReglages();
window.addEventListener('data-changed', (e) => {
  if (e.detail?.sujet === SUJET_REGLAGES) _relireReglages();
});

let _renderQueueListPending = null;
let _renderHistPending      = null;
const RENDER_THROTTLE_MS    = 200;

let _lastHistSave = 0;
const HIST_SAVE_THROTTLE_MS = 5_000;

function _getStoredHist() {
  try { return JSON.parse(localStorage.getItem(HIST_KEY) || '[]'); } catch { return []; }
}
function _saveHist(hist) {
  const now = Date.now();
  if (now - _lastHistSave < HIST_SAVE_THROTTLE_MS) return;
  _lastHistSave = now;
  try { localStorage.setItem(HIST_KEY, JSON.stringify(hist.slice(-MAX_HIST))); } catch {}
}
function _mergeHist(serverHist) {
  const stored  = _getStoredHist();
  const titres  = new Set(stored.map(h => h.titre + h.langue));
  const news    = serverHist.filter(h => !titres.has(h.titre + (h.langue||'')));
  const merged  = [...stored, ...news];
  _saveHist(merged);
  return merged;
}

function _bindDownloadDelegation() {
  const queueEl = document.getElementById('dl-queue');
  if (queueEl && !queueEl._dlBound) {
    queueEl._dlBound = true;
    const cardOf = (e) => e.target.closest('.queue-card');
    queueEl.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-act]');
      const card = btn && btn.closest('.queue-card');
      if (!btn || !card) return;
      const idx = parseInt(card.dataset.idx, 10);
      if (btn.dataset.act === 'up') window._dlMove(idx, -1);
      else if (btn.dataset.act === 'down') window._dlMove(idx, 1);
      else if (btn.dataset.act === 'remove') window._dlRemove(idx);
    });
    queueEl.addEventListener('dragstart', (e) => {
      const card = cardOf(e);
      if (card) window._dlDragStart(parseInt(card.dataset.idx, 10));
    });
    queueEl.addEventListener('dragover', (e) => {
      e.preventDefault();
      const card = cardOf(e);
      if (card) window._dlDragOver(card);
    });
    queueEl.addEventListener('dragleave', (e) => {
      const card = cardOf(e);
      if (card) window._dlDragLeave(card);
    });
    queueEl.addEventListener('drop', (e) => {
      e.preventDefault();
      const card = cardOf(e);
      if (card) window._dlDrop(parseInt(card.dataset.idx, 10));
    });
  }
  const activeEl = document.getElementById('dl-en-cours');
  if (activeEl && !activeEl._dlBound) {
    activeEl._dlBound = true;
    activeEl.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-act]');
      if (!btn) return;
      if (btn.dataset.act === 'pause') window.pauseDl();
      else if (btn.dataset.act === 'resume') window.reprendreDl();
      else if (btn.dataset.act === 'cancel') window.cancelDl();
    });
  }
}

export function renderQueue(state) {
  _bindDownloadDelegation();
  _lastQueueState = state;
  const { en_cours, queue = [], historique = [], elapsed = 0, en_pause = false } = state || {};

  _detectFinished(en_cours);
  renderEnCours(en_cours, elapsed, en_pause);

  const n = queue.length + (en_cours ? 1 : 0);
  const badge = document.getElementById('dl-badge');
  if (badge) { badge.textContent = n; badge.classList.toggle('hidden', n === 0); }

  const pageActive = document.getElementById('page-telechargements')?.classList.contains('active');

  if (pageActive) {
    if (_renderQueueListPending) clearTimeout(_renderQueueListPending);
    _renderQueueListPending = setTimeout(() => {
      renderQueueList(queue);
      const summaryEl = document.getElementById('dl-queue-summary');
      if (summaryEl && queue.length) {
        const totalEps = queue.reduce((s, item) => s + (item.nb_episodes || 1), 0);
        summaryEl.textContent = `${queue.length} anime${queue.length>1?'s':''} · ${totalEps} épisode${totalEps>1?'s':''}`;
      } else if (summaryEl) {
        summaryEl.textContent = '';
      }
    }, RENDER_THROTTLE_MS);

    if (_renderHistPending) clearTimeout(_renderHistPending);
    _renderHistPending = setTimeout(() => {
      const hist = _mergeHist(historique);
      renderHistorique(hist);
      _updateSessionStats(hist);
    }, RENDER_THROTTLE_MS);
  } else {
    _mergeHist(historique);
  }

  _fetchCovers(en_cours, queue);
}

function _detectFinished(en_cours) {

  if (_lastEnCours && !en_cours) {
    _playDoneChime();
    _animateProgressBar('done');
  }
  _lastEnCours = en_cours || null;
}

function _playDoneChime() {

  if (_settingsCache && _settingsCache.son_notif === false) return;
  try {
    if (!_audioCtx) {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) return;
      _audioCtx = new Ctor();
    }
    if (_audioCtx.state === 'suspended') _audioCtx.resume().catch(() => {});

    const ctx  = _audioCtx;
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.setValueAtTime(1100, ctx.currentTime + 0.1);
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
    osc.start(); osc.stop(ctx.currentTime + 0.4);
  } catch {}
}

async function _fetchCovers(en_cours, queue) {
  const now = Date.now();
  if (now - _coversCacheTs < COVERS_CACHE_TTL) return;

  if (_coversAbort) { try { _coversAbort.abort(); } catch {} }
  _coversAbort = new AbortController();
  let r = null;
  try {
    r = await api.get('/api/anime/covers', { signal: _coversAbort.signal });
  } catch { r = null; }
  if (r && typeof r === 'object') {
    _covers = r;
    _coversCacheTs = now;
  }
}

function renderEnCours(en_cours, elapsed, en_pause) {
  const el = document.getElementById('dl-en-cours');
  if (!el) return;
  if (!en_cours) {
    el.innerHTML = '<div class="dl-empty">Aucun téléchargement actif</div>';
    return;
  }

  const nom    = en_cours.episodes?.[0]?.titre || en_cours.nom || en_cours.ep?.titre || '?';
  const ep     = en_cours.episodes?.[0];
  const langue = ep?.langue || en_cours.langue || '';
  const nbEps  = en_cours.nb_episodes || 1;
  const sub    = ep ? etiquetteEpisode(ep) : langue;
  const cover  = _covers[nom] || '';

  el.innerHTML = `
    <div class="dl-active-card ${en_pause ? 'dl-paused' : ''}">
      <div class="dl-active-header">
        <div class="dl-actif-ligne">
          ${cover ? `<div class="dl-cover-ring" id="prog-ring"><img src="${esc(coverSrc(cover))}" class="dl-active-cover" alt="${esc(nom)}"></div>` : ''}
          <div class="flex-fill-min">
            <div class="dl-active-title ${en_pause ? 'paused' : ''}">${esc(nom)}</div>
            ${sub ? `<div class="dl-active-sub">${en_pause ? '⏸ En pause — ' : ''}${esc(sub)}${nbEps > 1 ? ` · ${nbEps} épisodes` : ''}</div>` : ''}
          </div>
        </div>
        <div class="dl-controls">
          ${en_pause
            ? `<button class="dl-btn dl-btn-play" data-act="resume">▶ Reprendre</button>`
            : `<button class="dl-btn dl-btn-pause" data-act="pause">⏸ Pause</button>`}
          <button class="dl-btn dl-btn-stop" data-act="cancel">✕ Arrêter</button>
        </div>
      </div>
      <div class="progress-bar" id="prog-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-label="Progression du téléchargement">
        <div class="progress-fill ${en_pause ? 'paused' : ''} dl-w-0" id="prog-fill"></div>
      </div>
      <div class="progress-info">
        <span id="prog-text">${en_pause ? 'En pause…' : 'Interception du stream…'}</span>

        <span id="prog-elapsed">${typeof window.__dlElapsed === 'number' ? fmtTime(window.__dlElapsed) : ''}</span>
      </div>
      <div class="progress-meta" id="prog-meta">
        <span id="prog-speed"></span>
        <span id="prog-eta"></span>
        <span id="prog-pct"></span>
      </div>
    </div>`;

  if (document.getElementById('page-telechargements')?.classList.contains('active')) {
    setTimeout(() => document.getElementById('dl-en-cours')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 100);
  }
}

function renderQueueList(queue) {
  const el = document.getElementById('dl-queue');
  if (!el) return;
  if (!queue.length) {
    el.innerHTML = '<div class="dl-empty">File d\'attente vide</div>';
    return;
  }

  const totalEps  = queue.reduce((s, item) => s + (item.nb_episodes || 1), 0);

  el.innerHTML = `
    <div class="dl-file-resume">
      <span id="dl-file-reste" data-eps="${totalEps}"></span>
      <span id="dl-file-fin"></span>
      <span>🎬 ${totalEps} épisode${totalEps>1?'s':''}</span>
    </div>
    <div class="queue-list">${queue.map((item, i) => {
      const isScan = !!item._scan;
      const nom   = item.episodes?.[0]?.titre || item.nom || item.ep?.titre || '?';
      const ep    = item.episodes?.[0];
      const langue = ep?.langue || item.lang || '';
      const nbEps = isScan ? (item.nb_chapitres || 0) : (item.nb_episodes || 1);
      const cover = _covers[nom] || '';
      return `
        <div class="queue-card" data-idx="${i}" draggable="true">
          ${cover ? `<img src="${esc(coverSrc(cover))}" class="queue-cover" alt="">` : '<div class="queue-cover-placeholder">🎌</div>'}
          ${i === 0 ? '<span class="queue-next-badge">Suivant</span>' : ''}
          <div class="queue-num">${i + 1}</div>
          <div class="queue-drag-handle" title="Glisser pour réorganiser">⠿</div>
          <div class="queue-info">
            <div class="queue-title">${esc(nom)}</div>
            <div class="queue-sub">${langue ? esc(String(langue).toUpperCase()) + ' · ' : ''}${isScan ? `📖 ${nbEps} chapitre${nbEps > 1 ? 's' : ''}` : `${nbEps} épisode${nbEps > 1 ? 's' : ''}`}</div>
          </div>
          <div class="queue-actions">
            <button type="button" class="queue-btn up"   title="Monter"    data-act="up" aria-label="Monter dans la file">↑</button>
            <button type="button" class="queue-btn down" title="Descendre" data-act="down" aria-label="Descendre dans la file">↓</button>
            <button type="button" class="queue-btn"      title="Supprimer" data-act="remove" aria-label="Retirer de la file">×</button>
          </div>
        </div>`;
    }).join('')}</div>`;

  _majResumeFile();
}

// Le resume de la file est reecrit a chaque seconde par le minuteur : il vit
// donc dans ses propres elements, pas dans le gabarit qui les cree.
function _majResumeFile() {
  const resteEl = document.getElementById('dl-file-reste');
  const finEl   = document.getElementById('dl-file-fin');
  if (!resteEl && !finEl) return;

  const epsFile = Number(resteEl?.dataset.eps || 0);
  const total   = eta.resteTotalS(epsFile);
  const mesure  = eta.estMesuree();
  const source  = mesure
    ? `D'après la durée médiane de ${eta.nbEchantillons()} épisode(s) déjà téléchargé(s)`
    : 'Aucun épisode mesuré : estimation par défaut de 8 min par épisode';

  if (resteEl) {
    resteEl.textContent = `⏱ ${mesure ? '' : '~'}${eta.fmtReste(total)}`;
    resteEl.title = source;
  }
  if (finEl) {
    finEl.textContent = `🕐 vers ${eta.heureDeFin(total)}`;
    finEl.title = source;
  }
}

/** Rafraichit les deux temps restants — appele chaque seconde par le minuteur. */
export function majEtaAffiche() {
  const etaEl = document.getElementById('prog-eta');
  if (etaEl) {
    const reste = eta.resteEpisodeS();
    etaEl.textContent = reste == null ? '' : '⏱ ' + eta.fmtReste(reste);
  }
  _majResumeFile();
}

function renderHistorique(historique) {
  const el = document.getElementById('dl-history');
  if (!el) return;

  if (!_clearHistoryBound) {
    const btn = document.getElementById('dl-clear-history');
    if (btn) {
      btn.addEventListener('click', async () => {
        localStorage.removeItem(HIST_KEY);
        if (_lastQueueState) _lastQueueState.historique = [];
        const histEl = document.getElementById('dl-history');
        if (histEl) histEl.innerHTML = '<div class="dl-empty">Aucun historique</div>';
        const stats = document.getElementById('dl-session-stats');
        if (stats) stats.textContent = '';
        try { await api.post('/api/download/historique/clear'); } catch {}
      });
      _clearHistoryBound = true;
    }
  }

  if (!historique.length) { el.innerHTML = '<div class="dl-empty">Aucun historique</div>'; return; }

  el.innerHTML = [...historique].reverse().map(h => `
    <div class="history-item dl-hist-anim">
      <div class="dl-hist-ligne">
        ${_covers[h.titre] ? `<img class="dl-hist-cover" src="${esc(coverSrc(_covers[h.titre]))}">` : ''}
        <div class="dl-hist-texte">
          <div class="dl-hist-titre">${esc(h.titre)}</div>
          <div class="dl-hist-sous">${esc(h.langue) || 'Toutes langues'}</div>
        </div>
      </div>
      <div class="history-badges">
        ${h.succes  ? `<span class="badge-ok">✅ ${h.succes}</span>`   : ''}
        ${h.skipped ? `<span class="badge-skip">⏭ ${h.skipped}</span>` : ''}
        ${h.echoues ? `<span class="badge-err">❌ ${h.echoues}</span>` : ''}
        ${h.annule  ? `<span class="badge-err">⛔ Annulé</span>`        : ''}
      </div>
    </div>`).join('');
}

function _updateSessionStats(hist) {
  const el = document.getElementById('dl-session-stats');
  if (!el) return;
  if (!hist.length) { el.textContent = ''; return; }
  const succes  = hist.reduce((s, h) => s + (h.succes  || 0), 0);
  const echoues = hist.reduce((s, h) => s + (h.echoues || 0), 0);
  const total   = succes + echoues;
  const pct     = total > 0 ? Math.round(succes / total * 100) : 0;
  el.innerHTML  = `${succes} ✅${echoues ? ` · ${echoues} ❌` : ''} · ${pct}% réussis`;
}

function _animateProgressBar(state) {
  const fill = document.getElementById('prog-fill');
  if (!fill) return;
  if (state === 'done')  { fill.style.background = 'linear-gradient(90deg, var(--green), #00e676)'; }
  if (state === 'error') { fill.style.background = 'linear-gradient(90deg, var(--red), #ff5252)'; }
}

let _actionLock = false;
async function withLock(fn) {
  if (_actionLock) return;
  _actionLock = true;
  try { await fn(); } catch(e) { toast(e.message, 'error'); }
  finally { setTimeout(() => { _actionLock = false; }, 800); }
}

document.addEventListener('keydown', e => {
  if (['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)) return;
  if (!document.getElementById('page-telechargements')?.classList.contains('active')) return;
  if (e.key === 'p' || e.key === 'P') {
    const enCours = document.getElementById('dl-en-cours');
    const isPaused = enCours?.querySelector('.dl-btn-play');
    isPaused ? window.reprendreDl() : window.pauseDl();
  }
  if (e.key === 'Escape') {
    if (document.getElementById('dl-en-cours')?.querySelector('.dl-active-card')) window.cancelDl();
  }
});

window.cancelDl    = () => withLock(async () => { await api.cancelDl();                       toast('⛔ Arrêté',     'info');    });
window.pauseDl     = () => withLock(async () => { await api.post('/api/download/pause');      toast('⏸ En pause',   'info');    });
window.reprendreDl = () => withLock(async () => { await api.post('/api/download/reprendre'); toast('▶ Reprise',    'success'); });

window._dlRemove = async (i) => {
  const card = document.querySelector(`.queue-card[data-idx="${i}"]`);
  if (card) { card.style.opacity = '0'; card.style.transform = 'translateX(20px)'; card.style.transition = 'all .25s'; }
  setTimeout(async () => {
    try { await api.delete(`/api/download/queue/${i}`); toast('🗑 Retiré', 'info'); }
    catch(e) { toast(e.message, 'error'); }
  }, 250);
};

window._dlMove = async (i, dir) => {
  const to = i + dir;
  try { await api.post('/api/download/deplacer', { from: i, to }); }
  catch(e) { toast(e.message, 'error'); }
};

const AUTOSCROLL_ZONE  = 90;
const AUTOSCROLL_SPEED = 18;

let _autoScrollRAF   = null;
let _autoScrollSpeed = 0;

function _getScrollContainer() {
  return document.querySelector('.main');
}

function _autoScrollLoop() {
  const cont = _getScrollContainer();
  if (cont && _autoScrollSpeed !== 0) {
    cont.scrollTop += _autoScrollSpeed;
  }
  _autoScrollRAF = requestAnimationFrame(_autoScrollLoop);
}

function _onDragAutoScroll(e) {
  const cont = _getScrollContainer();
  if (!cont) return;
  const rect = cont.getBoundingClientRect();
  const y    = e.clientY;

  if (y < rect.top + AUTOSCROLL_ZONE) {
    const ratio = (rect.top + AUTOSCROLL_ZONE - y) / AUTOSCROLL_ZONE;
    _autoScrollSpeed = -Math.ceil(ratio * AUTOSCROLL_SPEED);
  } else if (y > rect.bottom - AUTOSCROLL_ZONE) {
    const ratio = (y - (rect.bottom - AUTOSCROLL_ZONE)) / AUTOSCROLL_ZONE;
    _autoScrollSpeed = Math.ceil(ratio * AUTOSCROLL_SPEED);
  } else {
    _autoScrollSpeed = 0;
  }
}

function _startAutoScroll() {
  if (_autoScrollRAF !== null) return;
  _autoScrollSpeed = 0;
  document.addEventListener('dragover', _onDragAutoScroll);
  _autoScrollRAF = requestAnimationFrame(_autoScrollLoop);
}

function _stopAutoScroll() {
  document.removeEventListener('dragover', _onDragAutoScroll);
  if (_autoScrollRAF !== null) { cancelAnimationFrame(_autoScrollRAF); _autoScrollRAF = null; }
  _autoScrollSpeed = 0;
}

document.addEventListener('dragend', _stopAutoScroll);

window._dlDragStart = (i) => { _dragIdx = i; _startAutoScroll(); };
window._dlDragOver  = (el) => { el.classList.add('drag-over'); };
window._dlDragLeave = (el) => { el.classList.remove('drag-over'); };
window._dlDrop      = async (toIdx) => {
  _stopAutoScroll();
  document.querySelectorAll('.queue-card').forEach(c => c.classList.remove('drag-over'));
  if (_dragIdx === null || _dragIdx === toIdx) { _dragIdx = null; return; }
  try { await api.post('/api/download/deplacer', { from: _dragIdx, to: toIdx }); }
  catch(e) { toast(e.message, 'error'); }
  _dragIdx = null;
};

export function updateProgress(pct, text) {
  const fill = document.getElementById('prog-fill');
  const txt  = document.getElementById('prog-text');
  if (fill) {
    fill.style.width = Math.min(pct, 100) + '%';
    if (pct >= 100) fill.style.background = 'linear-gradient(90deg, var(--green), #00e676)';
    else fill.style.background = '';
  }

  const bar = document.getElementById('prog-bar');
  if (bar) {
    const v = Math.round(Math.min(Math.max(pct, 0), 100));
    bar.setAttribute('aria-valuenow', String(v));
    bar.setAttribute('aria-valuetext', `${v} %`);
  }

  const ring = document.getElementById('prog-ring');
  if (ring) ring.style.setProperty('--pct', Math.min(Math.max(pct, 0), 100));

  // Le debit reste lu dans la sortie du moteur : c'est une mesure, pas une
  // estimation. Le temps restant, lui, ne vient plus de `ETA 00:32` — cette
  // ligne n'existe que pour yt-dlp sans aria2c, et elle repart de zero a chaque
  // piste d'un format fusionne. Il est desormais calcule sur l'avancement reel,
  // quel que soit le moteur, et descend seconde par seconde.
  const speedMatch = text && text.match(/([\d.]+\s+(?:MB|KB|B)\/s)/);

  const speedEl = document.getElementById('prog-speed');
  const pctEl   = document.getElementById('prog-pct');

  if (speedEl) speedEl.textContent = speedMatch ? '⚡ ' + speedMatch[1] : '';
  if (pctEl)   pctEl.textContent   = pct > 0    ? pct.toFixed(1) + '%'  : '';
  majEtaAffiche();

  if (txt && text) txt.textContent = text;
}

function fmtTime(s) {
  if (!s) return '0m 00s';
  return `${Math.floor(s/60)}m ${String(s%60).padStart(2,'0')}s`;
}

window.addEventListener('dl-page-activated', async () => {
  if (_lastQueueState) {
    renderQueueList(_lastQueueState.queue || []);
    const hist = _mergeHist(_lastQueueState.historique || []);
    renderHistorique(hist);
    const summaryEl = document.getElementById('dl-queue-summary');
    const queue = _lastQueueState.queue || [];
    if (summaryEl && queue.length) {
      const totalEps = queue.reduce((s, item) => s + (item.nb_episodes || 1), 0);
      summaryEl.textContent = queue.length + ' anime' + (queue.length>1?'s':'') + ' · ' + totalEps + ' épisode' + (totalEps>1?'s':'');
    } else if (summaryEl) {
      summaryEl.textContent = '';
    }
    return;
  }
  try {
    const { api } = await import('../api.js');
    const state = await api.getDlStatus();
    if (state) renderQueue(state);
  } catch {}
});
