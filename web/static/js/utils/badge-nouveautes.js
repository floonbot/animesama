// Pastille de l'onglet Librairie : nouveaux episodes en attente. Tenue a jour
// par la veille du serveur (evenement SSE « nouveautes ») et par chaque
// verification faite depuis la librairie, pour ne jamais afficher un compte
// que la page contredit.
export function majBadgeNouveautes(total) {
  const badge = document.getElementById('lib-badge');
  if (!badge) return;
  const n = Number(total) || 0;
  badge.textContent = String(n);
  badge.classList.toggle('hidden', n <= 0);
  badge.title = n > 0 ? `${n} nouvel${n > 1 ? 's' : ''} épisode${n > 1 ? 's' : ''} à télécharger` : '';
}
