// Les quatre listes du compte anime-sama, cote front.
//
// Le champ `listes` est arrive apres coup : le cache disque du serveur et le
// cache de session du navigateur peuvent encore servir des entrees ecrites par
// la version precedente, ou il est absent. Une entree sans `listes` est un
// favori — c'etait le seul contenu de la charge utile avant.
//
// Les puces se deduisent de ce qui est reellement present : une liste vide sur
// le compte et une liste absente de la charge utile menent au meme endroit,
// une puce qui ne filtrerait rien.

export const LISTE_DEFAUT = 'favoris';

export const LISTES = [
  { id: 'favoris',    label: '⭐ Favoris' },
  { id: 'watchlist',  label: '👁 Watchlist' },
  { id: 'vus',        label: '✅ Vus' },
  { id: 'historique', label: '🕘 Historique' },
];

const _LABELS = new Map(LISTES.map((l) => [l.id, l.label]));

export function libelleListe(id) {
  return _LABELS.get(id) || id;
}

export function listesDe(anime) {
  const l = anime && anime.listes;
  return Array.isArray(l) && l.length ? l : [LISTE_DEFAUT];
}

export function dansListe(anime, id) {
  return listesDe(anime).includes(id);
}

export function compter(animes, id) {
  let n = 0;
  for (const a of animes || []) if (dansListe(a, id)) n++;
  return n;
}

// Les listes reellement peuplees, dans l'ordre de LISTES. Rendue vide quand une
// seule liste existe : il n'y a alors rien a choisir.
export function listesPresentes(animes) {
  const presentes = [];
  for (const { id } of LISTES) {
    const n = compter(animes, id);
    if (n) presentes.push({ id, label: _LABELS.get(id), n });
  }
  return presentes.length > 1 ? presentes : [];
}

export function filtrerListe(animes, id) {
  return (animes || []).filter((a) => dansListe(a, id));
}
