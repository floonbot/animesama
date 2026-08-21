
function initSpotlight() {
  let card = null, cx = 0, cy = 0, scheduled = false;
  document.addEventListener('pointermove', (e) => {
    const c = e.target.closest?.('.anime-card');
    if (!c) return;
    card = c; cx = e.clientX; cy = e.clientY;
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      const r = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${cx - r.left}px`);
      card.style.setProperty('--my', `${cy - r.top}px`);
    });
  }, { passive: true });
}

const BLURUP_SELECTOR =
  '.anime-card-img,.lib-cover-thumb,.recent-cover,.fav-list-cover,.anime-hero-cover,.updates-cover,.anime-du-jour-cover';

function initBlurUp() {

  document.addEventListener('load', (e) => {
    const img = e.target;
    if (img && img.tagName === 'IMG' && img.matches?.(BLURUP_SELECTOR)) {
      img.classList.add('blurup-anim');
    }
  }, true);
}

function initReveal() {
  if (!('IntersectionObserver' in window)) return;
  document.documentElement.classList.add('js-reveal');
  const io = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (en.isIntersecting) {
        en.target.classList.add('is-revealed');
        io.unobserve(en.target);
      }
    }
  }, { rootMargin: '0px 0px -6% 0px', threshold: 0.04 });

  const scan = () => document.querySelectorAll('[data-reveal]:not(.is-revealed)').forEach(el => io.observe(el));
  scan();
  return scan;
}

export function initEffects() {
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if (!reduce) {
    initSpotlight();
    initBlurUp();
  }
  const rescanReveal = initReveal();

  if (rescanReveal) window.__rescanReveal = rescanReveal;
}
