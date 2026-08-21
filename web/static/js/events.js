import { majEtaAffiche, renderQueue, updateProgress } from './pages/downloads.js';
import { majHomeEta, updateHomeDlProgress, updateHomeDlWidget } from './pages/home.js';
import { toast } from './components/toast.js';
import { api } from './api.js';
import * as eta from './utils/eta.js';
import { SUJET_LIBRAIRIE, signalerChangement } from './utils/vue-live.js';

// Vider le cache HTTP ne redessine rien : la vue qui regarde la librairie
// pendant un telechargement doit apprendre que son contenu a bouge.
function _invalidateLib() {
  api.invalidateCache('/api/anime/librairie');
  api.invalidateCache('/api/anime/covers');
  signalerChangement(SUJET_LIBRAIRIE);
}

let es              = null;
let _timerStart     = null;
let _timerTick      = null;
let _offlineBanner  = null;
let _reconnectTimer = null;

// Le diagnostic vit dans l'app et n'ouvre donc pas une seconde EventSource :
// il se contente de ces deux evenements, republies depuis l'unique flux.
const RELAYED_EVENTS = [
  'queue_updated', 'episode_start', 'episode_done', 'anime_done', 'dl_annule',
];

function _relayer(type) {
  window.dispatchEvent(new CustomEvent('sse-activity', { detail: { type } }));
}

function _relayerEtat(live) {
  window.dispatchEvent(new CustomEvent('sse-state', { detail: { live } }));
}

function _parse(raw) {
  try { return JSON.parse(raw); }
  catch (e) {
    console.warn('[sse] JSON invalide ignoré:', e?.message);
    return null;
  }
}

export function initSSE() {
  connect();
  window.addEventListener('offline', () => showOfflineBanner('Connexion réseau perdue'));
  window.addEventListener('online',  () => { hideOfflineBanner(); connect(); });
}

function connect() {

  if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }

  if (es && es.readyState !== EventSource.CLOSED) return;
  if (es) { try { es.close(); } catch(e){} }

  es = new EventSource('/api/events');

  for (const type of RELAYED_EVENTS) es.addEventListener(type, () => _relayer(type));

  es.addEventListener('queue_updated', e => {
    const data = _parse(e.data);
    if (!data) return;
    // Avant renderQueue : le resume de la file lit le temps restant, qui doit
    // deja savoir si l'on est en pause.
    eta.signalerPause(!!data.en_pause);
    if (!data.en_cours) eta.arreterEpisode();
    renderQueue(data);
    updateHomeDlWidget(data);

    if (!data.en_cours || data.en_pause) {
      stopTimer();
    }
  });

  es.addEventListener('episode_start', e => {
    const d = _parse(e.data);
    if (!d) return;
    eta.demarrerEpisode(d);
    const label = d.ep || d.nom || '';
    const total = d.total || 1;
    const idx   = (d.index || 0) + 1;
    const subEl = document.querySelector('.dl-active-sub');
    if (subEl) subEl.textContent = `Épisode ${idx}/${total} — ${label}`;
    const txtEl = document.getElementById('prog-text');
    if (txtEl) txtEl.textContent = 'Interception du stream…';
    const fill = document.getElementById('prog-fill');
    if (fill) fill.style.width = '0%';

    startTimer(0);
  });

  es.addEventListener('episode_progress', e => {
    const d = _parse(e.data);
    if (!d) return;

    if (!_timerTick) startTimer(0);
    eta.noterProgression(d.pct || 0);
    updateProgress(d.pct || 0, d.line || '');
    updateHomeDlProgress(d.pct || 0);
  });

  es.addEventListener('episode_done', e => {
    const d = _parse(e.data);
    if (!d) return;

    // Un episode saute dure une fraction de seconde et un echec s'arrete en
    // route : ni l'un ni l'autre ne dit combien de temps prend un episode.
    eta.terminerEpisode(!!d.succes && !d.skipped);
    stopTimer();
    if (d.skipped)     { toast(`⏭ ${d.ep || d.nom} déjà présent`, 'info'); }
    else if (d.succes) {
      toast(`✅ ${d.ep || d.nom} téléchargé !`, 'success');
      sendNotif('✅ Téléchargement terminé', d.ep || d.nom || '');
      _invalidateLib();
    }
    else { toast(`❌ ${d.ep || d.nom} : ${d.erreur || 'échoué'}`, 'error', 6000); }
  });

  es.addEventListener('anime_done', e => {
    const d = _parse(e.data);
    if (!d) return;
    stopTimer();
    const msg = `🎌 ${d.titre} — ${d.succes} ✅ ${d.echoues ? d.echoues + ' ❌' : ''} ${d.skipped ? d.skipped + ' ⏭' : ''}`;
    toast(msg.trim(), d.echoues ? 'error' : 'success', 6000);
    sendNotif('🎌 Anime terminé', `${d.titre} — ${d.succes} épisodes téléchargés`);
    _invalidateLib();
  });

  es.addEventListener('dl_annule', e => {
    stopTimer();
    const d = _parse(e.data) || {};
    toast(`⛔ ${d.nom || 'Téléchargement'} annulé`, 'info');
  });

  es.onerror = () => {
    try { es.close(); } catch {}
    stopTimer();
    _relayerEtat(false);
    showOfflineBanner('Connexion au serveur perdue — reconnexion dans 5s…');

    if (_reconnectTimer) clearTimeout(_reconnectTimer);
    _reconnectTimer = setTimeout(() => {
      _reconnectTimer = null;
      hideOfflineBanner();
      connect();
    }, 5000);
  };

  es.addEventListener('open', () => {
    _relayerEtat(true);
    hideOfflineBanner();
  });
}

function sendNotif(titre, corps) {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'granted') {
    // Un carre de 256 : bg-dark.png etait un fond de 1536x1024 et 2 Mo, que
    // Windows ecrasait dans une vignette.
    try { new Notification(titre, { body: corps, icon: '/img/notif.png' }); }
    catch {}
  } else if (Notification.permission !== 'denied') {
    Notification.requestPermission();
  }
}

function showOfflineBanner(msg) {
  if (_offlineBanner) {

    const span = _offlineBanner.querySelector('span');
    if (span) span.textContent = `⚠️ ${msg}`;
    return;
  }
  _offlineBanner = document.createElement('div');
  _offlineBanner.id = 'offline-banner';
  _offlineBanner.setAttribute('role', 'status');
  _offlineBanner.setAttribute('aria-live', 'polite');
  const _s = document.createElement('span');
  _s.textContent = `⚠️ ${msg}`;
  _offlineBanner.appendChild(_s);
  document.body.appendChild(_offlineBanner);
}

function hideOfflineBanner() {
  if (_offlineBanner) { _offlineBanner.remove(); _offlineBanner = null; }
}

function startTimer(initialElapsed = 0) {
  stopTimer();
  _timerStart = Date.now() - (initialElapsed * 1000);
  const tick = () => {
    const s = Math.floor((Date.now() - _timerStart) / 1000);

    window.__dlElapsed = s;
    const el = document.getElementById('prog-elapsed');
    if (el) el.textContent = fmtTime(s);
    // Le temps restant se recalcule sur la meme horloge : sans cela il resterait
    // fige entre deux lignes du moteur au lieu de descendre.
    majEtaAffiche();
    majHomeEta();
  };
  tick();

  _timerTick = setInterval(tick, 250);
}

function stopTimer() {
  if (_timerTick) { clearInterval(_timerTick); _timerTick = null; }
  _timerStart = null;
}

function fmtTime(s) {
  const m = Math.floor(s / 60);
  return `${m}m ${String(s % 60).padStart(2,'0')}s`;
}
