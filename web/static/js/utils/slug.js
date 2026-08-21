// Le slug d'une oeuvre est le dernier segment de son URL de catalogue. Il vit
// ici plutot que dans pages/scans.js : les cartes de favoris en ont besoin pour
// annoncer quoi precharger, et importer scans.js pour deux lignes ramenerait
// tout son chunk dans le bundle principal.
export function slugFromUrl(url) {
  const m = /\/catalogue\/([^/?#]+)/.exec(String(url || ''));
  return m ? m[1] : '';
}
