export function initMenu() {
  const toggle  = document.getElementById('menu-toggle');
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (!toggle || !sidebar) return;

  const sync  = () => toggle.setAttribute('aria-expanded', sidebar.classList.contains('open') ? 'true' : 'false');
  const close = () => { sidebar.classList.remove('open'); sync(); };
  const open  = () => { sidebar.classList.add('open'); sync(); };

  toggle.addEventListener('click', () => {
    sidebar.classList.contains('open') ? close() : open();
  });
  overlay && overlay.addEventListener('click', close);

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && sidebar.classList.contains('open')) close();
  });

  sidebar.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      if (window.innerWidth <= 768) close();
    });
  });
}
