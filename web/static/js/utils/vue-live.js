// Une vue qui se remet a jour toute seule, sur le patron de pages/diag.js.
//
// Trois regles, et c'est tout ce que fait ce module :
//   1. on ne redessine que si la vue est devant l'utilisateur ;
//   2. sinon on marque l'etat sale et on redessine au retour ;
//   3. les rafales sont regroupees — un anime de douze episodes emet douze
//      episode_done, ce n'est pas douze reconstructions de la librairie.
//
// Pas d'intervalle de sondage ici : une information qui n'arrive pas doit
// passer par le flux SSE, pas par une interrogation en boucle du serveur.

export const SUJET_LIBRAIRIE = 'librairie';
export const SUJET_REGLAGES = 'reglages';

const DELAI_REGROUPEMENT_MS = 400;

export function signalerChangement(sujet, detail = {}) {
  window.dispatchEvent(new CustomEvent('data-changed', { detail: { sujet, ...detail } }));
}

export function abonnerVue({ page, sujets, rafraichir, delaiMs = DELAI_REGROUPEMENT_MS }) {
  let sale = false;
  let timer = null;

  const visible = () =>
    !document.hidden && !!document.getElementById('page-' + page)?.classList.contains('active');

  const redessiner = () => {
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      if (!visible()) return;
      sale = false;
      try { rafraichir(); } catch (e) { console.warn('[vue-live] ' + page + ' :', e?.message); }
    }, delaiMs);
  };

  const marquerSale = () => {
    sale = true;
    if (visible()) redessiner();
  };

  // La page se recharge aussi par son propre chemin — le clic de navigation.
  // Sans ce signal, un retour sur une vue marquee sale rechargeait deux fois :
  // une par le clic, une par le rattrapage 400 ms plus tard.
  const marquerPropre = () => {
    sale = false;
    if (timer) { clearTimeout(timer); timer = null; }
  };

  const auRetour = () => { if (sale && visible()) redessiner(); };

  window.addEventListener('data-changed', (e) => {
    if (sujets.includes(e.detail?.sujet)) marquerSale();
  });
  window.addEventListener('page-changed', auRetour);
  document.addEventListener('visibilitychange', auRetour);

  return { marquerSale, marquerPropre, estVisible: visible, estSale: () => sale };
}
