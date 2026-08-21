// Comment nommer un episode a l'ecran, en un seul endroit.
//
// Piege : `ep.saison` n'est PAS un numero de saison, c'est l'index du panneau
// sur la fiche du site (engine/scraping/episodes.py, _construire_episodes).
// DanMachi expose « Film » en huitieme panneau : l'ecrire « S08 » inventait une
// saison qui n'existe nulle part, alors que le journal et le dossier sur le
// disque disent tous deux « Film ». `saison_nom` porte le libelle reel du site
// et c'est lui qui fait foi ; le numero n'est qu'un repli quand il manque.

export function etiquetteSaison(ep) {
  if (!ep) return '';
  return ep.saison_nom || `Saison ${String(ep.saison || 1).padStart(2, '0')}`;
}

export function etiquetteEpisode(ep) {
  if (!ep) return '';
  const num = `E${String(ep.episode || 0).padStart(3, '0')}`;
  const langue = ep.langue ? ` ${ep.langue}` : '';
  return `${etiquetteSaison(ep)} · ${num}${langue}`;
}
