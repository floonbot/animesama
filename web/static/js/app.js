import './utils/inline-styles.js';
import { initRouter } from './router.js';
import { initNavArrows } from './components/nav-arrows.js';
import { initModals }   from './components/modal.js';
import { initMenu }     from './components/menu.js';
import { watchForPlaceholders } from './components/sakura.js';
import { initSSE }      from './events.js';
import { checkAuth, initLogoutButtons } from './pages/home.js';
import { loadFavoris }  from './pages/favorites.js';
import { loadLibrairie } from './pages/library.js';
import { initDiag }    from './pages/diag.js';
import { initSettings } from './pages/settings.js';
import { initSearch }   from './pages/search.js';
import { initFocusTrap } from './utils/focus-trap.js';
import { hideBootLoader } from './utils/boot.js';
import { initEffects } from './utils/effects.js';
import { initPrefetchAuRepos, initPrefetchOnHover } from './utils/prefetch.js';

document.addEventListener('DOMContentLoaded', async () => {
  const _bootFailsafe = setTimeout(hideBootLoader, 6000);

  initEffects();
  initPrefetchOnHover();
  // Expose : sans prise, un test ne peut que courir apres la veille de 2 s.
  window.__prefetchAuRepos = initPrefetchAuRepos();
  initRouter();
  initNavArrows();
  initModals();
  initMenu();
  initFocusTrap();
  initDiag();
  initSettings();
  initSSE();
  await checkAuth();
  initLogoutButtons();
  initSearch();

  clearTimeout(_bootFailsafe);
  requestAnimationFrame(hideBootLoader);

  watchForPlaceholders();

  const main = document.querySelector('.main');
  if (main) {
    let scrollEndTimer = null;
    main.addEventListener('scroll', () => {
      if (!main.classList.contains('is-scrolling')) main.classList.add('is-scrolling');
      clearTimeout(scrollEndTimer);
      scrollEndTimer = setTimeout(() => main.classList.remove('is-scrolling'), 140);
    }, { passive: true });
  }

  document.querySelector('[data-page="favoris"]')?.addEventListener('click', loadFavoris);
  document.getElementById('btn-refresh-fav')?.addEventListener('click', () => loadFavoris(true));
  document.querySelector('[data-page="librairie"]')?.addEventListener('click', () => loadLibrairie());

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    ['modal-login', 'modal-anime'].forEach(id => {
      document.getElementById(id)?.classList.add('hidden');
    });
  });

  // Les notifications partent du serveur (engine/utils/notifications.py) :
  // WebView2 refuse d'office l'API Notification du web.
});
