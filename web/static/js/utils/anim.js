export function animateCount(el, target) {
  if (!el) return;
  target = Number(target) || 0;
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (target <= 0 || reduce || typeof requestAnimationFrame !== 'function') {
    el.textContent = String(target);
    return;
  }
  const duration = 600;
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  let start = null;
  function frame(now) {
    if (start === null) start = now;
    const p = Math.min((now - start) / duration, 1);
    el.textContent = String(Math.round(ease(p) * target));
    if (p < 1) requestAnimationFrame(frame);
    else el.textContent = String(target);
  }
  requestAnimationFrame(frame);
}
