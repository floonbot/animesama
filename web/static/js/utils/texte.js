// Filtrage tolerant partage par les favoris et la librairie.
//
// Trois pieges que « nom.toLowerCase().includes(q) » ne passait pas :
// les accents (« Pokémon » ne repondait pas a « pokemon »), la ponctuation
// (« Re:Zero » ne repondait pas a « re zero ») et l'ordre des mots
// (« senki youjo » ne trouvait pas « Youjo Senki »). La decomposition NFKD
// reproduit ici ce que normaliser_nom fait deja cote Python.
//
// Cout : la normalisation est faite une fois par anime, a la construction de
// l'index, jamais par frappe — sans quoi le facteur 10 gagne sur le filtrage
// de la librairie disparaitrait.

import { esc } from './escape.js';

const DIACRITIQUES = /[̀-ͯ]/g;
const NON_ASCII = /[^\x00-\x7F]/;

// NFKD est l'identite sur l'ASCII et n'y laisse aucun diacritique a retirer :
// l'index de la librairie normalise plusieurs milliers de noms de fichiers,
// presque tous en ASCII pur.
function _plier(s) {
  const src = String(s || '');
  if (!NON_ASCII.test(src)) return src.toLowerCase();
  return src.normalize('NFKD').replace(DIACRITIQUES, '').toLowerCase();
}

// Repli caractere par caractere, longueur garantie identique a l'original :
// c'est ce qui permet de surligner « Poké » quand l'utilisateur a tape « poke ».
// Les rares caracteres qui s'etalent en NFKD (« ﬁ » -> « fi ») gardent leur
// forme d'origine plutot que de decaler tout l'alignement.
//
// Le NFKD par caractere coute cher — 4,8x le prix d'un simple toLowerCase sur
// une passe de surlignage — et la quasi-totalite des noms de fichiers sont en
// ASCII pur, ou les deux resultats coincident exactement.
function _plierAligne(s) {
  const src = String(s || '');
  if (!NON_ASCII.test(src)) return src.toLowerCase();
  let out = '';
  for (const ch of src) {
    const plie = _plier(ch);
    out += plie.length === ch.length ? plie : ch.toLowerCase();
  }
  return out.length === src.length ? out : src.toLowerCase();
}

// Texte comparable : accents replies, ponctuation reduite a une espace,
// espaces multiples ecrases. « Re:Zero — Saison 2 » -> « re zero saison 2 ».
export function normaliserTexte(s) {
  return _plier(s).replace(/[^a-z0-9]+/g, ' ').trim();
}

// Cle d'identite d'une oeuvre, pour rapprocher un favori d'un dossier sur le
// disque. Sans espaces : le site ecrit « Re:Zero », le disque « Re Zero ».
export function cleAnime(nom) {
  return _plier(nom).replace(/[^a-z0-9]/g, '');
}

export function jetonsRequete(q) {
  const n = normaliserTexte(q);
  return n ? n.split(' ') : [];
}

// Tous les jetons presents, dans n'importe quel ordre.
export function correspond(texteNormalise, jetons) {
  for (const j of jetons) {
    if (!texteNormalise.includes(j)) return false;
  }
  return true;
}

// Classement volontairement grossier : prefixe exact, puis debut de mot, puis
// simple sous-chaine. Une distance d'edition couterait plus cher qu'elle ne
// rapporte sur des listes de quelques centaines de titres.
export function rang(texteNormalise, jetons) {
  if (!jetons.length) return 0;
  const premier = jetons[0];
  if (texteNormalise.startsWith(premier)) return 0;
  if (texteNormalise.includes(' ' + premier)) return 1;
  return 2;
}

function _fusionner(plages) {
  plages.sort((a, b) => a[0] - b[0]);
  const out = [];
  for (const p of plages) {
    const dernier = out[out.length - 1];
    if (dernier && p[0] <= dernier[1]) dernier[1] = Math.max(dernier[1], p[1]);
    else out.push([p[0], p[1]]);
  }
  return out;
}

// Rend le texte echappe, chaque occurrence de chaque jeton entouree de balise.
// Sans le repli aligne, chercher « poke » laissait « Pokémon » sans surlignage.
export function surlignerJetons(texte, jetons, ouvrir, fermer) {
  const brut = String(texte ?? '');
  if (!jetons.length) return esc(brut);
  const plie = _plierAligne(brut);
  const plages = [];
  for (const j of jetons) {
    let i = plie.indexOf(j);
    while (i !== -1) {
      plages.push([i, i + j.length]);
      i = plie.indexOf(j, i + j.length);
    }
  }
  if (!plages.length) return esc(brut);
  let out = '';
  let curseur = 0;
  for (const [debut, fin] of _fusionner(plages)) {
    out += esc(brut.slice(curseur, debut)) + ouvrir + esc(brut.slice(debut, fin)) + fermer;
    curseur = fin;
  }
  return out + esc(brut.slice(curseur));
}
