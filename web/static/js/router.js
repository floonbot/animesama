import { setPage } from './components/theme.js';
import { modaliteClavier, poserFocus } from './utils/focus.js';

const PAGE_LABELS = {
  home:            '🏠 Accueil',
  favoris:         '⭐ Favoris',
  recherche:       '🔍 Recherche',
  telechargements: '⬇️ Téléchargements',
  librairie:       '📁 Librairie',
  parametres:      '⚙️ Paramètres',
  diag:            '🩺 Diagnostic',
};

let _history = ['home'];
let _pos     = 0;
let _vtActive = false;

function moveNavRail(navEl) {
  const nav = document.querySelector('.nav');
  if (!nav) return;
  let rail = nav.querySelector('.nav-rail-indicator');
  if (!rail) {
    rail = document.createElement('div');
    rail.className = 'nav-rail-indicator';
    nav.prepend(rail);
    nav.classList.add('has-rail');
  }
  if (!navEl) return;
  rail.style.height = `${navEl.offsetHeight}px`;
  rail.style.transform = `translateY(${navEl.offsetTop}px)`;
  rail.classList.add('show');
}

export function initRouter() {
  document.querySelectorAll('.nav-item').forEach(item => {
    item.setAttribute('role', 'button');
    item.setAttribute('tabindex', '0');
    item.addEventListener('click', e => {
      e.preventDefault();
      if (item.dataset.page) navigateTo(item.dataset.page);
    });
    item.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        item.click();
      }
    });
  });
  moveNavRail(document.querySelector('.nav-item.active'));
}

export function navigateTo(page, fromHistory = false) {
  if (document.startViewTransition && !_vtActive) {
    _vtActive = true;
    const clear = () => { _vtActive = false; };
    document.startViewTransition(() => _navigateTo(page, fromHistory)).finished.then(clear, clear);
  } else {
    _navigateTo(page, fromHistory);
  }
}

function _navigateTo(page, fromHistory = false) {
  document.querySelectorAll('.nav-item').forEach(n => {
    n.classList.remove('active');
    n.removeAttribute('aria-current');
  });
  document.querySelectorAll('.page').forEach(p => {
    p.classList.remove('active');
    p.style.display = '';
  });

  const navEl = document.querySelector(`.nav-item[data-page="${page}"]`);
  navEl?.classList.add('active');
  navEl?.setAttribute('aria-current', 'page');
  moveNavRail(navEl);
  const target = document.getElementById(`page-${page}`);
  if (target) {
    target.classList.add('active');
    target.style.display = '';
  }

  document.querySelector('.main')?.scrollTo({ top: 0, behavior: 'instant' });

  setPage(page);

  if (target) {
    // Le titre prend le focus pour que le lecteur d'ecran annonce la vue et que
    // le Tab suivant reparte de son debut. Au clavier l'anneau dit ou le focus
    // a atterri ; a la souris il n'apprend rien.
    const heading = target.querySelector('.page-title') || target;
    heading.setAttribute('tabindex', '-1');
    poserFocus(heading, { anneau: modaliteClavier() });
  }

  if (!fromHistory) {
    if (_history[_pos] !== page) {
      _history = _history.slice(0, _pos + 1);
      _history.push(page);
      _pos = _history.length - 1;
    }
  }
  _notifyHistoryChange();

  window.dispatchEvent(new CustomEvent('page-changed', { detail: { page } }));

  if (page === 'telechargements') {
    window.dispatchEvent(new CustomEvent('dl-page-activated'));
  }
}

export function goBack() {
  if (!canGoBack()) return;
  _pos--;
  navigateTo(_history[_pos], true);
}

export function goForward() {
  if (!canGoForward()) return;
  _pos++;
  navigateTo(_history[_pos], true);
}

export function canGoBack()    { return _pos > 0; }
export function canGoForward() { return _pos < _history.length - 1; }

export function getHistoryList(direction) {
  const out = [];
  if (direction === 'back') {
    for (let i = _pos - 1; i >= 0; i--) {
      out.push({ page: _history[i], label: PAGE_LABELS[_history[i]] || _history[i], offset: i - _pos });
    }
  } else {
    for (let i = _pos + 1; i < _history.length; i++) {
      out.push({ page: _history[i], label: PAGE_LABELS[_history[i]] || _history[i], offset: i - _pos });
    }
  }
  return out;
}

export function goToOffset(offset) {
  const target = _pos + offset;
  if (target < 0 || target >= _history.length) return;
  _pos = target;
  navigateTo(_history[_pos], true);
}

function _notifyHistoryChange() {
  window.dispatchEvent(new CustomEvent('nav-history-changed', {
    detail: { canBack: canGoBack(), canForward: canGoForward() },
  }));
}
