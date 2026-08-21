import { poserFocus } from './focus.js';

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),' +
  'textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

function visibleFocusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter(el => el.offsetParent !== null);
}

function openModals() {
  return [...document.querySelectorAll('.modal')].filter(
    m => !m.classList.contains('hidden') && m.offsetParent !== null,
  );
}

let _restoreFocus = null;

// La modale s'ouvre souvent depuis une carte — un <div>, que le clic ne
// focalise pas. Le focus a rendre est donc reste sur le titre de la page, et le
// rendre apres un Echap y dessinait un anneau : le geste etait au clavier, mais
// la cible n'est atteignable par aucun Tab. On ne garde l'anneau que sur ce qui
// est reellement tabulable — un bouton, un champ — ou l'utilisateur peut agir.
function _rendreFocus(el) {
  if (!el || typeof el.focus !== 'function') return;
  try {
    poserFocus(el, { anneau: el.tabIndex >= 0 });
  } catch { /* element retire du DOM entre-temps */ }
}

export function initFocusTrap() {

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const modals = openModals();
    const modal = modals[modals.length - 1];
    if (!modal) return;
    const f = visibleFocusables(modal);
    if (!f.length) return;
    const first = f[0];
    const last = f[f.length - 1];
    const active = document.activeElement;
    if (!modal.contains(active)) {
      e.preventDefault();
      first.focus();
      return;
    }
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  }, true);

  const obs = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.addedNodes) {
        if (node.nodeType === 1 && node.classList?.contains('modal')) {
          _restoreFocus = document.activeElement;
          const f = visibleFocusables(node);
          if (f.length) f[0].focus();
        }
      }
      for (const node of m.removedNodes) {
        if (node.nodeType === 1 && node.classList?.contains('modal')) {
          _rendreFocus(_restoreFocus);
          _restoreFocus = null;
        }
      }
    }
  });
  obs.observe(document.body, { childList: true });

  for (const modal of document.querySelectorAll('.modal')) {
    const mobs = new MutationObserver(() => {
      const visible = !modal.classList.contains('hidden') && modal.offsetParent !== null;
      if (visible) {
        if (!modal.contains(document.activeElement)) {
          _restoreFocus = document.activeElement;
          const f = visibleFocusables(modal);
          if (f.length) f[0].focus();
        }
      } else if (_restoreFocus) {
        _rendreFocus(_restoreFocus);
        _restoreFocus = null;
      }
    });
    mobs.observe(modal, { attributes: true, attributeFilter: ['class'] });
  }
}
