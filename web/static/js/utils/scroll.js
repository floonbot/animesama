export function softScrollTop(el) {
  if (!el) return;
  const t = el.getBoundingClientRect().top;
  if (t < -40 || t > 160) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
