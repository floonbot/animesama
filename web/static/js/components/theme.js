const BG_IMAGES = {
  home:            '/img/fond-accueil.webp',
  favoris:         '/img/fond-favoris.webp',
  recherche:       '/img/fond-recherche.webp',
  telechargements: '/img/fond-telechargements.webp',
  librairie:       '/img/fond-librairie.webp',
  parametres:      '/img/fond-parametres.webp',
  diag:            '/img/fond-diagnostic.webp',
  default:         '/img/fond-accueil.webp',
};

export function setPage(page) {
  const bg = BG_IMAGES[page] || BG_IMAGES.default;
  const el = document.getElementById('page-bg');
  if (el) el.style.backgroundImage = `url('${bg}')`;
}
