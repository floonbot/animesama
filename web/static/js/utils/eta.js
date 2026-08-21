/**
 * Temps restant, mesuré au lieu d'être supposé.
 *
 * Deux estimations coexistaient, toutes deux fausses :
 *
 *   - sur l'épisode en cours, l'ETA était attrapé au lasso dans la sortie texte
 *     de yt-dlp (`/ETA\s+([\w]+)/`). Il n'apparaît donc jamais quand le
 *     téléchargement passe par interception, N_m3u8DL-RE ou ffmpeg, et il ne
 *     descend pas entre deux lignes du moteur ;
 *   - sur la file, `totalEps * 8` — huit minutes par épisode, en dur, quelle que
 *     soit la connexion, l'hôte ou la qualité.
 *
 * Ce module remplace les deux par de la mesure. Il ne connaît pas le DOM : il
 * reçoit les événements du flux SSE et rend des secondes.
 *
 * **Épisode en cours** : la vitesse d'avancement du pourcentage sur une fenêtre
 * glissante d'une minute. Le reste se déduit du pourcentage manquant, puis
 * décroît tout seul entre deux événements — c'est ce qui donne le compte à
 * rebours « 30 min → 28 → 25 » au lieu d'un nombre figé.
 *
 * **Épisodes suivants** : la médiane des durées réellement observées, gardée
 * dans le stockage local. La médiane et non la moyenne : un épisode à 17 minutes
 * sur un hôte bridé ne doit pas tirer l'estimation des vingt autres. Tant
 * qu'aucun épisode n'est allé au bout, on retombe sur les huit minutes
 * historiques — mais `estMesuree()` dit alors que le chiffre est supposé, et
 * l'affichage le marque.
 *
 * Trois pièges que le calcul traite explicitement :
 *
 *   - **le pourcentage repart à zéro** au milieu d'un épisode, une fois par
 *     piste d'un format fusionné. Sans remise à zéro de la fenêtre, l'avance
 *     devient négative et le reste part à l'infini. Le moteur connaît le même
 *     piège côté serveur, cf. `SurveillantDebit._redemarrer_observation` ;
 *   - **la pause** fige l'avancement mais pas l'horloge. L'épisode traversé par
 *     une pause est écarté des échantillons, sinon la médiane enfle ;
 *   - **les épisodes sautés** finissent en une fraction de seconde. Comptés, ils
 *     effondreraient la médiane.
 */

const CLE_DUREES = 'dl_durees_episodes';
const MAX_ECHANTILLONS = 20;

// Ce que l'ancien calcul appliquait à tout le monde. Conservé comme repli, et
// signalé comme tel tant qu'aucune mesure n'existe.
const DUREE_SUPPOSEE_S = 8 * 60;

// Bornes d'un échantillon crédible : en deçà c'est un saut ou un échec
// instantané, au-delà c'est le délai de garde global du worker (3 h 30).
const ECHANTILLON_MIN_S = 5;
const ECHANTILLON_MAX_S = 3 * 3600 + 1800;

const FENETRE_MS = 60_000;
const OBSERVATION_MIN_S = 5;
const AVANCE_MIN_PCT = 0.5;
const RECUL_TOLERE_PCT = 5;

let _points = [];        // { t, pct } de l'épisode en cours
let _debutEpisode = 0;
let _pollueParPause = false;
let _enCours = false;
let _index = 0;
let _total = 1;

function _lire() {
  try {
    const brut = JSON.parse(localStorage.getItem(CLE_DUREES) || '[]');
    return Array.isArray(brut) ? brut.filter(n => typeof n === 'number' && n > 0) : [];
  } catch { return []; }
}

function _ecrire(liste) {
  try { localStorage.setItem(CLE_DUREES, JSON.stringify(liste.slice(-MAX_ECHANTILLONS))); } catch {}
}

export function demarrerEpisode(d) {
  _points = [];
  _debutEpisode = Date.now();
  _pollueParPause = false;
  _enCours = true;
  _index = Number(d && d.index) || 0;
  _total = Math.max(1, Number(d && d.total) || 1);
}

export function noterProgression(pct) {
  if (!_enCours) {
    // Une progression sans démarrage : l'onglet a été ouvert alors qu'un
    // téléchargement tournait déjà. Mieux vaut estimer depuis maintenant que
    // ne rien afficher.
    _debutEpisode = Date.now();
    _pollueParPause = true;   // durée partielle : pas un échantillon valable
    _enCours = true;
  }
  const p = Number(pct);
  if (!Number.isFinite(p)) return;

  const dernier = _points[_points.length - 1];
  if (dernier && p < dernier.pct - RECUL_TOLERE_PCT) _points = [];

  const t = Date.now();
  _points.push({ t, pct: p });
  while (_points.length > 2 && t - _points[1].t > FENETRE_MS) _points.shift();
}

export function signalerPause(enPause) {
  if (!enPause) return;
  _pollueParPause = true;
  _points = [];        // l'avancement reprendra sa mesure à la reprise
}

export function terminerEpisode(reussi) {
  const debut = _debutEpisode;
  const pollue = _pollueParPause;
  _points = [];
  _debutEpisode = 0;
  _pollueParPause = false;
  _enCours = false;
  if (!reussi || pollue || !debut) return;

  const s = Math.round((Date.now() - debut) / 1000);
  if (s < ECHANTILLON_MIN_S || s > ECHANTILLON_MAX_S) return;
  _ecrire([..._lire(), s]);
}

export function arreterEpisode() {
  _points = [];
  _debutEpisode = 0;
  _pollueParPause = false;
  _enCours = false;
}

function _vitessePctParS() {
  if (_points.length < 2) return 0;
  const a = _points[0];
  const b = _points[_points.length - 1];
  const dt = (b.t - a.t) / 1000;
  const dp = b.pct - a.pct;
  if (dt < OBSERVATION_MIN_S || dp < AVANCE_MIN_PCT) return 0;
  return dp / dt;
}

/** Secondes restantes sur l'épisode en cours, ou `null` si rien ne se mesure. */
export function resteEpisodeS() {
  const v = _vitessePctParS();
  if (!v) return null;
  const dernier = _points[_points.length - 1];
  const restePct = Math.max(0, 100 - dernier.pct);
  // Retrancher le temps écoulé depuis le dernier événement : sans lui, le
  // chiffre resterait figé entre deux lignes du moteur au lieu de descendre.
  const depuis = (Date.now() - dernier.t) / 1000;
  return Math.max(0, restePct / v - depuis);
}

export function dureeMedianeEpisodeS() {
  const e = _lire();
  if (!e.length) return DUREE_SUPPOSEE_S;
  const tri = [...e].sort((a, b) => a - b);
  const m = Math.floor(tri.length / 2);
  return tri.length % 2 ? tri[m] : Math.round((tri[m - 1] + tri[m]) / 2);
}

export function estMesuree() {
  return _lire().length > 0;
}

export function nbEchantillons() {
  return _lire().length;
}

export function episodesRestantsItemCourant() {
  return _enCours ? Math.max(0, _total - _index - 1) : 0;
}

/**
 * Secondes avant que tout soit fini : le reste de l'épisode en cours, les
 * épisodes qui le suivent dans le même anime, puis ceux de la file.
 */
export function resteTotalS(episodesEnFile = 0) {
  const mediane = dureeMedianeEpisodeS();
  const reste = resteEpisodeS();
  const courant = reste == null ? (_enCours ? mediane : 0) : reste;
  return courant + (episodesRestantsItemCourant() + Math.max(0, episodesEnFile)) * mediane;
}

export function fmtReste(s) {
  if (s == null) return '';
  const t = Math.max(0, Math.round(s));
  if (t < 60) return `${t} s`;
  const min = Math.round(t / 60);
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const r = min % 60;
  return r ? `${h} h ${String(r).padStart(2, '0')}` : `${h} h`;
}

export function heureDeFin(s) {
  if (s == null) return '';
  const d = new Date(Date.now() + Math.max(0, s) * 1000);
  return `${d.getHours()}h${String(d.getMinutes()).padStart(2, '0')}`;
}

// Réservé aux tests : repartir d'un état vierge sans recharger la page.
export function _reinitialiser() {
  arreterEpisode();
  try { localStorage.removeItem(CLE_DUREES); } catch {}
}
