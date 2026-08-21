// Une puce de filtre se desarme au second clic.
//
// Quatre barres d'outils — librairie (type, langue, listes), favoris et
// recherche (langue) — repetaient la meme selection exclusive stricte : le
// bouton clique devenait actif, et revenir a l'ensemble obligeait a viser le
// bouton neutre au lieu de re-cliquer celui qu'on venait d'activer.
//
// N'appeler que sur des barres qui possedent une option neutre (« Tout »,
// « Tous », « Toutes », de valeur vide) : un tri garde toujours une option
// active, et un onglet aussi — les desarmer ne voudrait rien dire.

export function basculerFiltre(boutons, btn, actuel, cle) {
  const valeur = btn.dataset[cle] ?? '';
  const suivant = actuel === valeur ? '' : valeur;
  for (const b of boutons) {
    const on = (b.dataset[cle] ?? '') === suivant;
    b.classList.toggle('active', on);
    b.setAttribute('aria-pressed', String(on));
  }
  return suivant;
}
