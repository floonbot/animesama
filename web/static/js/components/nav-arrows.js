import { esc } from '../utils/escape.js';
import {
  goBack, goForward, canGoBack, canGoForward,
  getHistoryList, goToOffset,
} from '../router.js';

const HOLD_DELAY = 450;

let _btnBack    = null;
let _btnForward = null;
let _menu       = null;

export function initNavArrows() {
  _btnBack    = document.getElementById('nav-back');
  _btnForward = document.getElementById('nav-forward');
  if (!_btnBack || !_btnForward) return;

  _bindButton(_btnBack,    'back',    goBack);
  _bindButton(_btnForward, 'forward', goForward);

  window.addEventListener('nav-history-changed', _refreshState);
  _refreshState();

  document.addEventListener('click', e => {
    if (_menu && !_menu.contains(e.target) &&
        e.target !== _btnBack && e.target !== _btnForward) _closeMenu();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') _closeMenu(); });
}

function _bindButton(btn, direction, onClick) {
  let holdTimer  = null;
  let didOpenMenu = false;

  const startHold = (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    didOpenMenu = false;
    holdTimer = setTimeout(() => {
      didOpenMenu = true;
      _openMenu(btn, direction);
    }, HOLD_DELAY);
  };

  const endHold = () => {
    if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; }
  };

  btn.addEventListener('mousedown', startHold);
  btn.addEventListener('mouseup',   endHold);
  btn.addEventListener('mouseleave', endHold);

  btn.addEventListener('touchstart', startHold, { passive: true });
  btn.addEventListener('touchend',   endHold);
  btn.addEventListener('touchcancel', endHold);

  btn.addEventListener('click', (e) => {
    e.preventDefault();
    if (didOpenMenu) { didOpenMenu = false; return; }
    onClick();
  });

  btn.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    _openMenu(btn, direction);
  });
}

function _refreshState() {
  if (_btnBack)    _btnBack.classList.toggle('nav-arrow-disabled',    !canGoBack());
  if (_btnForward) _btnForward.classList.toggle('nav-arrow-disabled', !canGoForward());
}

function _openMenu(anchorBtn, direction) {
  _closeMenu();

  const items = getHistoryList(direction);
  if (!items.length) return;

  _menu = document.createElement('div');
  _menu.className = 'nav-history-menu';
  _menu.innerHTML = items.map(it => `
    <button class="nav-history-item" data-offset="${it.offset}">
      ${esc(it.label)}
    </button>`).join('');

  document.body.appendChild(_menu);

  const r = anchorBtn.getBoundingClientRect();
  _menu.style.top  = (r.bottom + 6) + 'px';
  _menu.style.left = r.left + 'px';

  _menu.querySelectorAll('.nav-history-item').forEach(el => {
    el.addEventListener('click', () => {
      goToOffset(parseInt(el.dataset.offset, 10));
      _closeMenu();
    });
  });
}

function _closeMenu() {
  if (_menu) { _menu.remove(); _menu = null; }
}
