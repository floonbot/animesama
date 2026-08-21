import { api }   from '../api.js';
import { toast } from './toast.js';

export function initModals() {
  document.getElementById('login-form')?.addEventListener('submit', (e) => e.preventDefault());

  // On bascule l'attribut `type` plutot que de remplacer le champ : les
  // gestionnaires de mots de passe se fient a `autocomplete` et a l'identite du
  // noeud, et un champ recree perdrait les deux.
  const masquerMdp = () => {
    const champ = document.getElementById('login-password');
    const btn   = document.getElementById('login-password-voir');
    if (champ) champ.type = 'password';
    if (btn) {
      btn.setAttribute('aria-pressed', 'false');
      btn.setAttribute('aria-label', 'Afficher le mot de passe');
      btn.title = 'Afficher le mot de passe';
      btn.textContent = '👁';
    }
  };

  document.getElementById('login-password-voir')?.addEventListener('click', () => {
    const champ = document.getElementById('login-password');
    const btn   = document.getElementById('login-password-voir');
    if (!champ || !btn) return;
    if (champ.type === 'password') {
      champ.type = 'text';
      btn.setAttribute('aria-pressed', 'true');
      btn.setAttribute('aria-label', 'Masquer le mot de passe');
      btn.title = 'Masquer le mot de passe';
      btn.textContent = '🙈';
    } else {
      masquerMdp();
    }
    champ.focus();
  });

  // La modale se ferme aussi par Echap (app.js) et s'ouvre depuis les reglages,
  // sans passer par closeLogin : suivre la classe est le seul endroit qui les
  // couvre tous. Un mot de passe en clair ne doit jamais survivre a une
  // fermeture, quel qu'en soit le chemin.
  const modalLogin = document.getElementById('modal-login');
  const oublierSaisie = () => {
    const err = document.getElementById('login-error');
    if (err) { err.classList.add('hidden'); err.textContent = ''; }
    const champ = document.getElementById('login-password');
    if (champ) champ.value = '';
    masquerMdp();
  };
  if (modalLogin) {
    new MutationObserver(() => {
      if (modalLogin.classList.contains('hidden')) oublierSaisie();
    }).observe(modalLogin, { attributes: true, attributeFilter: ['class'] });
  }

  const openLogin  = () => modalLogin?.classList.remove('hidden');
  const closeLogin = () => modalLogin?.classList.add('hidden');

  document.getElementById('hero-connect')?.addEventListener('click', async () => {
    const s = await api.getAuthStatus().catch(() => ({ connected: false }));
    s.connected ? document.querySelector('[data-page="favoris"]')?.click() : openLogin();
  });

  const userCard = document.getElementById('user-card');
  if (userCard) {
    const openIfDisconnected = async () => {
      const s = await api.getAuthStatus().catch(() => ({ connected: false }));
      if (!s.connected) openLogin();
    };
    const syncRole = () => {
      if (userCard.classList.contains('not-connected')) {
        userCard.setAttribute('role', 'button');
        userCard.setAttribute('tabindex', '0');
        userCard.setAttribute('aria-label', 'Se connecter');
      } else {
        userCard.removeAttribute('role');
        userCard.removeAttribute('tabindex');
        userCard.removeAttribute('aria-label');
      }
    };
    new MutationObserver(syncRole).observe(userCard, { attributes: true, attributeFilter: ['class'] });
    syncRole();
    userCard.addEventListener('click', openIfDisconnected);
    userCard.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openIfDisconnected(); }
    });
  }

  document.getElementById('login-cancel')?.addEventListener('click', closeLogin);
  document.getElementById('login-close')?.addEventListener('click', closeLogin);
  document.getElementById('login-backdrop')?.addEventListener('click', closeLogin);
  document.getElementById('login-password')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('login-submit')?.click();
  });

  document.getElementById('login-submit')?.addEventListener('click', async () => {
    const pseudo = document.getElementById('login-pseudo').value.trim();
    const pwd   = document.getElementById('login-password').value;
    const errEl = document.getElementById('login-error');
    const btn   = document.getElementById('login-submit');
    if (!pseudo || !pwd) { errEl.textContent = 'Pseudo et mot de passe requis'; errEl.classList.remove('hidden'); return; }
    btn.disabled = true; btn.textContent = '⏳ Connexion...'; errEl.classList.add('hidden');
    try {
      const r = await api.post('/api/auth/login', { pseudo, password: pwd });
      if (r.ok) {
        closeLogin();
        const _dn = r.username?.includes('.') ? r.username.split('.')[0] : r.username;
        toast(`✅ Connecté — ${_dn}`, 'success', 4000);
        const { checkAuth } = await import('../pages/home.js');
        await checkAuth();
        const { loadFavoris } = await import('../pages/favorites.js');
        await loadFavoris();
        document.querySelector('[data-page="favoris"]')?.click();
      } else {
        errEl.textContent = r.message || 'Identifiants incorrects';
        errEl.classList.remove('hidden');
      }
    } catch(e) { errEl.textContent = e.message; errEl.classList.remove('hidden'); }
    finally { btn.disabled = false; btn.textContent = '⚡ Connexion'; }
  });

  document.getElementById('anime-close')?.addEventListener('click', closeAnime);
  document.getElementById('anime-backdrop')?.addEventListener('click', closeAnime);
}

export function openAnime(anime) {
  document.getElementById('modal-anime').classList.remove('hidden');
  document.getElementById('modal-anime-content').innerHTML =
    '<div data-s="text-align:center;padding:30px"><span class="spinner"></span> Chargement…</div>';
  import('../pages/anime-modal.js').then(m => m.loadAnimeModal(anime));
}

function closeAnime() {
  document.getElementById('modal-anime').classList.add('hidden');
}
