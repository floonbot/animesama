// Poser le focus par programme sans faire mentir l'anneau de :focus-visible.
//
// L'anneau ne se decide pas au CSS : les navigateurs appliquent une heuristique
// et, sur un element focalise par script, Chromium le dessine des que la
// derniere interaction etait un appui touche. Deux endroits deplacent le focus
// ici — le routeur vers le titre de la vue, et le piege a focus au retour d'une
// modale — et tous deux visent des elements en tabindex="-1", qu'aucun Tab ne
// peut atteindre. Fermer une fiche avec Echap dessinait donc un rectangle bleu
// autour du titre de la page, que personne n'avait demande.
//
// Chaque appelant declare si l'anneau informe dans SON cas ; la regle
// :focus-visible globale, elle, reste intacte pour tout ce qui est tabulable.

let _clavier = false;
document.addEventListener('pointerdown', () => { _clavier = false; }, true);
document.addEventListener('keydown',     () => { _clavier = true;  }, true);

export function modaliteClavier() {
  return _clavier;
}

export function poserFocus(el, { anneau = false } = {}) {
  if (!el || typeof el.focus !== 'function') return;
  el.classList.toggle('focus-discret', !anneau);
  el.focus({ preventScroll: true });
}
