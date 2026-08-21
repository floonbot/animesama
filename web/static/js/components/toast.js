import { esc } from '../utils/escape.js';

const MAX_TOASTS = 5;

const ICONS = {
  success: '✅',
  error:   '❌',
  warning: '⚠️',
  info:    'ℹ️',
};

export function toast(msg, type = 'info', duration = 3500) {
  const container = document.getElementById('toasts');
  if (!container) return;

  let live = container.querySelectorAll('.toast:not(.removing)');
  while (live.length >= MAX_TOASTS) {
    _dismiss(live[0]);
    live = container.querySelectorAll('.toast:not(.removing)');
  }

  const el = document.createElement('div');

  el.className = `toast ${type}`;

  el.style.setProperty('--toast-duration', `${duration}ms`);

  el.innerHTML = `
    <span class="toast-icon" aria-hidden="true">${ICONS[type] || 'ℹ️'}</span>
    <div class="toast-body">
      <div class="toast-msg">${esc(msg)}</div>
    </div>
    <button class="toast-close" aria-label="Fermer">✕</button>
  `;

  el.querySelector('.toast-close').addEventListener('click', () => _dismiss(el));

  container.appendChild(el);

  let remaining = duration;
  let startedAt = Date.now();

  const arm = () => {
    startedAt = Date.now();
    el.dataset.timer = setTimeout(() => _dismiss(el), remaining);
  };
  const hold = () => {
    if (el.classList.contains('toast-paused')) return;
    clearTimeout(Number(el.dataset.timer));
    remaining -= Date.now() - startedAt;
    el.classList.add('toast-paused');
  };
  const release = () => {
    if (!el.classList.contains('toast-paused')) return;
    el.classList.remove('toast-paused');
    if (remaining <= 0) { _dismiss(el); return; }
    arm();
  };

  el.addEventListener('mouseenter', hold);
  el.addEventListener('mouseleave', release);
  el.addEventListener('focusin', hold);
  el.addEventListener('focusout', release);

  arm();
}

function _dismiss(el) {
  if (!el || el.classList.contains('removing')) return;
  clearTimeout(Number(el.dataset.timer));
  el.classList.add('removing');

  el.addEventListener('animationend', () => el.remove(), { once: true });

  setTimeout(() => el.remove(), 350);
}
