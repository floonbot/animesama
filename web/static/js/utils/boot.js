
export function hideBootLoader() {
  const el = document.getElementById('boot-loader');
  if (!el || el.classList.contains('boot-hide')) return;
  el.classList.add('boot-hide');
  setTimeout(() => el.remove(), 650);
}
