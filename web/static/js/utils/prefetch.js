import { api } from '../api.js';

// Le survol laisse 140 ms avant de lancer la requete : assez pour ne pas
// precharger toute une grille au passage de la souris. Mais pointerover
// n'existe pas au toucher, et un clic rapide ou une validation au clavier
// n'attendent pas 140 ms — d'ou le second declencheur sur pointerdown, qui
// precede click et ne coute rien de plus : getCached dedoublonne les appels
// en vol par sa promesse.
const DELAI_SURVOL_MS = 140;

// La fiche vit dans un chunk separe : sans ce reveil, le premier clic paie
// l'aller-retour du module avant meme d'afficher le squelette.
let _moduleDemande = false;
function _reveillerModule() {
  if (_moduleDemande) return;
  _moduleDemande = true;
  import('../pages/anime-modal.js').catch(() => { _moduleDemande = false; });
}

function _precharger(cible) {
  if (!cible) return;
  const url = cible.dataset.prefetch;
  const slug = cible.dataset.prefetchScan;
  if (!url && !slug) return;
  _reveillerModule();
  if (url) api.prefetchEpisodes(url);
  if (slug) api.prefetchScan(slug);
}

function _cible(e) {
  return e.target.closest?.('[data-prefetch], [data-prefetch-scan]');
}

export function initPrefetchOnHover() {
  let timer = null;
  document.addEventListener('pointerover', (e) => {
    const cible = _cible(e);
    if (!cible) return;
    clearTimeout(timer);
    timer = setTimeout(() => _precharger(cible), DELAI_SURVOL_MS);
  }, { passive: true });

  document.addEventListener('pointerdown', (e) => {
    clearTimeout(timer);
    _precharger(_cible(e));
  }, { passive: true });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    _precharger(document.activeElement?.closest?.('[data-prefetch], [data-prefetch-scan]'));
  }, { passive: true });
}

// --------------------------------------------------------------------------
// Prechargement au repos.
//
// C11 a mesure que l'ouverture d'une fiche coute ~850 ms de scraping distant, et
// qu'un survol prealable la ramene a ~54 ms. Le survol ne couvre que la carte
// visee ; precharger celles qui sont deja a l'ecran pendant que l'utilisateur ne
// fait rien est le levier restant.
//
// Le garde-fou est l'anti-ban, pas le navigateur : le site nous coupe si on le
// mitraille. D'ou trois bornes strictes — n'agir qu'apres un vrai temps mort,
// espacer les requetes, et plafonner par periode de repos. Une seule requete est
// en vol a la fois ; getCached dedoublonne le reste.
const REPOS_MS = 2000;
const ENTRE_DEUX_MS = 1200;
const PLAFOND_PAR_REPOS = 6;

function _visibleDansLaFenetre(el) {
  const r = el.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return false;
  const h = window.innerHeight || document.documentElement.clientHeight;
  const w = window.innerWidth || document.documentElement.clientWidth;
  return r.bottom > 0 && r.top < h && r.right > 0 && r.left < w;
}

export function initPrefetchAuRepos({ compteur } = {}) {
  const deja = new Set();
  let veille = null;
  let enCours = null;

  const cartesVisibles = () =>
    [...document.querySelectorAll('[data-prefetch], [data-prefetch-scan]')]
      .filter((el) => {
        const cle = el.dataset.prefetch || el.dataset.prefetchScan;
        return cle && !deja.has(cle) && _visibleDansLaFenetre(el);
      });

  async function _balayer() {
    let n = 0;
    for (const el of cartesVisibles()) {
      if (n >= PLAFOND_PAR_REPOS || document.visibilityState !== 'visible') break;
      const cle = el.dataset.prefetch || el.dataset.prefetchScan;
      deja.add(cle);
      _precharger(el);
      compteur?.(cle);
      n += 1;
      // Espacer, meme la derniere : une rafale serree est ce qui reveille
      // l'anti-ban, pas le nombre total.
      await new Promise((r) => setTimeout(r, ENTRE_DEUX_MS));
    }
    // La grille peut arriver apres la veille — celle des favoris attend la
    // librairie, qui depasse les 2 s des qu'elle est grosse. Le balayage tombait
    // alors sur une page vide, et plus rien ne le rearmait : qui ne touche plus
    // a rien ne prechargeait jamais cette page. On ne repasse que tant qu'il n'y
    // a aucune carte, donc jamais en boucle sur une page deja servie.
    if (n === 0 && !document.querySelector('[data-prefetch], [data-prefetch-scan]')) {
      relancerLaVeille();
    }
  }

  // Rend la promesse du balayage en vol plutot que de refuser : un appelant qui
  // attend la fin en obtient une, et l'unicite du balayage reste garantie.
  function balayer() {
    if (enCours) return enCours;
    if (document.visibilityState !== 'visible') return Promise.resolve();
    enCours = _balayer().finally(() => { enCours = null; });
    return enCours;
  }

  const relancerLaVeille = () => {
    clearTimeout(veille);
    veille = setTimeout(balayer, REPOS_MS);
  };

  // Toute action de l'utilisateur repousse le balayage : le prechargement ne
  // doit jamais disputer la bande passante a une requete qu'il attend.
  for (const ev of ['pointerdown', 'pointermove', 'keydown', 'scroll', 'wheel']) {
    document.addEventListener(ev, relancerLaVeille, { passive: true, capture: true });
  }
  document.addEventListener('visibilitychange', relancerLaVeille);
  window.addEventListener('hashchange', relancerLaVeille);
  relancerLaVeille();

  return { balayer, relancerLaVeille };
}
