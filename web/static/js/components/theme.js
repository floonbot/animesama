const BG_IMAGES = {
  home:            '/img/bg-dark.webp',
  favoris:         '/img/favoris-dark.webp',
  recherche:       '/img/search-dark.webp',
  telechargements: '/img/download-dark.webp',
  librairie:       '/img/library-dark.webp',
  parametres:      '/img/settings-dark.webp',
  diag:            '/img/diag-dark.webp',
  default:         '/img/bg-dark.webp',
};

export function setPage(page) {
  const bg = BG_IMAGES[page] || BG_IMAGES.default;
  const el = document.getElementById('page-bg');
  if (el) el.style.backgroundImage = `url('${bg}')`;
}
