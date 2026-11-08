import { api } from '../api.js';

// Partage par la fiche des favoris (anime-modal) et celle de la librairie
// (netflix) : le texte arrive apres la fiche, qui ne l'attend jamais.
export function chargerSynopsis({ url, nom }) {
  const qs = url ? `url=${encodeURIComponent(url)}` : `nom=${encodeURIComponent(nom || '')}`;
  return api.getCached(`/api/anime/synopsis?${qs}`, 600000)
    .then(r => (r && r.synopsis) || '')
    .catch(() => '');
}

// Replie a quelques lignes, comme sur le site ; « Voir plus » n'apparait que si
// le texte deborde vraiment.
export function remplirSynopsis(bloc, texte) {
  if (!bloc || !bloc.isConnected) return;
  if (!texte) { bloc.hidden = true; return; }
  const p = bloc.querySelector('.synopsis-texte');
  const bouton = bloc.querySelector('.synopsis-plus');
  p.textContent = texte;
  bloc.hidden = false;
  if (!bouton) return;
  bouton.hidden = p.scrollHeight <= p.clientHeight + 1;
  bouton.onclick = () => {
    const ouvert = p.classList.toggle('synopsis-ouvert');
    bouton.textContent = ouvert ? 'Voir moins' : 'Voir plus';
    bouton.setAttribute('aria-expanded', String(ouvert));
  };
}

export function blocSynopsis(classe = '') {
  return `<div class="synopsis ${classe}" hidden>
    <p class="synopsis-texte"></p>
    <button type="button" class="synopsis-plus" aria-expanded="false" hidden>Voir plus</button>
  </div>`;
}
