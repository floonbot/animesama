import { esc } from '../../utils/escape.js';
import { coverSrc } from '../../utils/cover.js';
import { api } from '../../api.js';
import { toast } from '../../components/toast.js';
import { slugify } from './format.js';
import { state } from './state.js';

// check-updates coûte cher : la réponse vient d'un cache de 5 min côté serveur,
// et le front la garde entre deux passages sur la page. Un chiffre sans âge se
// lit comme « à l'instant », ce qui a déjà coûté une enquête entière.
export function ageVerification(checkedAt) {
  if (!checkedAt) return '';
  const s = Math.max(0, Math.floor(Date.now() / 1000) - checkedAt);
  if (s < 60)    return "à l'instant";
  if (s < 3600)  return `il y a ${Math.floor(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`;
  return `il y a ${Math.floor(s / 86400)} j`;
}

// L'age vivait en infobulle : invisible a la souris comme au clavier, alors
// que c'est precisement ce qui distingue « 0 nouveau » de « 0 nouveau il y a
// deux heures ». Il descend donc dans la carte, sous le libelle.
function _poserFraicheur(statEl) {
  if (!statEl) return;
  const age = ageVerification(state.updatesCheckedAt);
  if (!age) return;
  const base = statEl.title ? `${statEl.title}\n` : '';
  statEl.title = `${base}Vérifié ${age}`;
  let ligne = statEl.querySelector('.lib-stat-age');
  if (!ligne) {
    ligne = document.createElement('span');
    ligne.className = 'lib-stat-age';
    statEl.appendChild(ligne);
  }
  ligne.textContent = `Vérifié ${age}`;
}

export async function checkNouveauxEpisodes(forceRefresh = false) {
  const statEl = document.getElementById('lstat-nouveaux');
  if (statEl) {
    statEl.innerHTML = `
      <span class="lib-stat-icon"><span class="spinner lib-ico-18"></span></span>
      <span class="lib-stat-val lib-txt-dim-13">…</span>
      <span class="lib-stat-lbl">Vérification</span>`;
  }

  try {
    const data = await api.checkUpdates(forceRefresh);

    if (data.non_connecte) {
      if (statEl) {
        statEl.innerHTML = `<span class="lib-stat-icon">🔌</span><span class="lib-stat-val lib-txt-muted-13">—</span><span class="lib-stat-lbl">Non connecté</span>`;
      }
      return;
    }

    state.updatesParAnime = {};
    for (const a of data.animes || []) {
      state.updatesParAnime[a.nom] = a;
    }
    state.updatesCheckedAt = data.checked_at || 0;

    const total = data.total_nouveaux || 0;
    const nonVerifies = data.non_verifies || 0;

    if (statEl) {
      if (total === 0 && nonVerifies > 0) {
        statEl.innerHTML = `<span class="lib-stat-icon">⚠️</span><span class="lib-stat-val lib-txt-amber-13">${nonVerifies}</span><span class="lib-stat-lbl">Non vérifiés</span>`;
        statEl.style.cursor = 'pointer';
        statEl.title = `${nonVerifies} anime(s) non vérifiés (site lent / limité). Clique pour réessayer.`;
        statEl.onclick = () => checkNouveauxEpisodes(true);
      } else if (total === 0) {
        statEl.innerHTML = `<span class="lib-stat-icon">✅</span><span class="lib-stat-val lib-txt-green">0</span><span class="lib-stat-lbl">À jour</span>`;
        statEl.onclick = null;
        statEl.style.cursor = '';
      } else {
        statEl.innerHTML = `
          <span class="lib-stat-icon">🆕</span>
          <span class="lib-stat-val lib-txt-ram">${total}</span>
          <span class="lib-stat-lbl">Nouveaux ép.</span>`;
        statEl.style.cursor = 'pointer';
        statEl.title = 'Cliquer pour voir les nouveaux épisodes';
        statEl.onclick = showUpdatesModal;
      }
      _poserFraicheur(statEl);
    }

    injectUpdateBadges();

    if (total > 0 && forceRefresh) {
      toast(`🆕 ${total} nouvel${total > 1 ? 's' : ''} épisode${total > 1 ? 's' : ''} disponible${total > 1 ? 's' : ''}`, 'info');
    }
  } catch(e) {
    console.warn('check-updates échec:', e);
    if (statEl) {
      statEl.innerHTML = `<span class="lib-stat-icon">⚠️</span><span class="lib-stat-val lib-txt-muted-13">?</span><span class="lib-stat-lbl">Indispo</span>`;
    }
  }
}

export function majStatNouveaux() {
  const statEl = document.getElementById('lstat-nouveaux');
  if (!statEl) return;
  const total = Object.values(state.updatesParAnime).reduce((s, a) => s + (a.nouveaux_count || 0), 0);
  if (total === 0) {
    statEl.innerHTML = `<span class="lib-stat-icon">✅</span><span class="lib-stat-val lib-txt-green">0</span><span class="lib-stat-lbl">À jour</span>`;
    statEl.onclick = null;
    statEl.style.cursor = '';
  } else {
    statEl.innerHTML = `
      <span class="lib-stat-icon">🆕</span>
      <span class="lib-stat-val lib-txt-ram">${total}</span>
      <span class="lib-stat-lbl">Nouveaux ép.</span>`;
    statEl.style.cursor = 'pointer';
    statEl.title = 'Cliquer pour voir les nouveaux épisodes';
    statEl.onclick = showUpdatesModal;
  }
  _poserFraicheur(statEl);
}

export function injectUpdateBadges() {

  for (const nom in state.updatesParAnime) {
    const update = state.updatesParAnime[nom];
    const card = document.getElementById(`lib-${slugify(nom)}`);
    if (!card) continue;

    const headerActions = card.querySelector('.lib-header > div:last-child');
    if (!headerActions) continue;

    if (headerActions.querySelector('.lib-new-badge')) continue;

    const count = update.nouveaux_count;
    const badge = document.createElement('button');
    badge.className = 'lib-new-badge';
    badge.dataset.action = 'dl-new';
    badge.dataset.nom = nom;
    badge.title = `Télécharger ${count} nouvel${count > 1 ? 's' : ''} épisode${count > 1 ? 's' : ''}`;
    badge.innerHTML = `🆕 ${count}`;

    const counter = headerActions.querySelector('.lib-count');
    if (counter) {
      headerActions.insertBefore(badge, counter);
    } else {
      headerActions.appendChild(badge);
    }

    card.classList.add('lib-has-updates');
  }
}

export async function telechargerNouveauxEpisodes(nomAnime, btn) {
  const update = state.updatesParAnime[nomAnime];
  if (!update || !update.nouveaux_episodes?.length) {
    toast('Aucun nouvel épisode pour cet anime', 'info');
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner lib-ico-11"></span>`;
  }

  try {
    const eps = update.nouveaux_episodes;
    await api.addToQueue(eps[0], eps);
    toast(`✅ ${eps.length} nouvel${eps.length > 1 ? 's' : ''} épisode${eps.length > 1 ? 's' : ''} ajouté${eps.length > 1 ? 's' : ''} à la queue`, 'success');

    delete state.updatesParAnime[nomAnime];
    if (btn) btn.remove();

    const card = document.getElementById(`lib-${slugify(nomAnime)}`);
    if (card) card.classList.remove('lib-has-updates');

    const total = Object.values(state.updatesParAnime).reduce((s, a) => s + a.nouveaux_count, 0);
    const statEl = document.getElementById('lstat-nouveaux');
    if (statEl) {
      if (total === 0) {
        statEl.innerHTML = `<span class="lib-stat-icon">✅</span><span class="lib-stat-val lib-txt-green">0</span><span class="lib-stat-lbl">À jour</span>`;
        statEl.onclick = null;
        statEl.style.cursor = '';
      } else {
        const valEl = statEl.querySelector('.lib-stat-val');
        if (valEl) valEl.textContent = total;
      }
    }
  } catch(e) {
    toast(`❌ ${e.message}`, 'error');
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `🆕 ${update.nouveaux_count}`;
    }
  }
}

export function showUpdatesModal() {
  const animes = Object.values(state.updatesParAnime);
  if (!animes.length) return;

  const totalEps = animes.reduce((sum, a) => sum + a.nouveaux_count, 0);

  const html = `
    <div class="modal" id="modal-updates" role="dialog" aria-modal="true">
      <div class="modal-backdrop"></div>
      <div class="modal-box modal-wide">
        <button class="modal-close" id="updates-close" aria-label="Fermer" type="button">✕</button>
        <h2>🆕 Nouveaux épisodes disponibles</h2>
        <p class="lib-intro">
          ${totalEps} nouvel${totalEps > 1 ? 's' : ''} épisode${totalEps > 1 ? 's' : ''} sur ${animes.length} anime${animes.length > 1 ? 's' : ''} de ta librairie.
          ${state.updatesCheckedAt ? `<span class="lib-txt-muted-13">Vérifié ${esc(ageVerification(state.updatesCheckedAt))}.</span>` : ''}
        </p>

        <div class="updates-list">
          ${animes.map(a => `
            <div class="updates-item" data-nom="${esc(a.nom)}">
              ${a.image
                ? `<img src="${esc(coverSrc(a.image))}" class="updates-cover" alt="${esc(a.nom)}" loading="lazy" decoding="async">`
                : `<div class="updates-cover updates-cover-placeholder">🎌</div>`}
              <div class="updates-info">
                <div class="updates-title">${esc(a.nom)}</div>
                <div class="updates-eps">
                  ${a.nouveaux_episodes.slice(0, 6).map(e => {
                    const epTxt = `E${String(e.episode).padStart(2,'0')}`;
                    const base = e.saison_label
                      ? `${esc(e.saison_label)} · ${epTxt}`
                      : `S${String(e.saison).padStart(2,'0')}${epTxt}`;
                    const lbl = e.type === 'nouvelle_saison' ? `${base} (nouvelle saison)` : base;
                    const langTxt = e.langue ? ` <span class="updates-ep-lang">${esc(e.langue)}</span>` : '';
                    return `<span class="updates-ep">${lbl}${langTxt}</span>`;
                  }).join('')}
                  ${a.nouveaux_episodes.length > 6 ? `<span class="updates-ep-more">+${a.nouveaux_episodes.length - 6}</span>` : ''}
                </div>
              </div>
              <button class="btn btn-sm btn-ram updates-dl-btn" data-nom="${esc(a.nom)}">
                ⬇️ ${a.nouveaux_count}
              </button>
            </div>
          `).join('')}
        </div>

        <div class="modal-actions">
          <button class="btn btn-ghost" id="updates-cancel" type="button">Fermer</button>
          <button class="btn btn-ram" id="updates-dl-all" type="button">⬇️ Tout télécharger (${totalEps})</button>
        </div>
      </div>
    </div>`;

  const wrapper = document.createElement('div');
  wrapper.innerHTML = html;
  const modal = wrapper.firstElementChild;
  document.body.appendChild(modal);

  const close = () => modal.remove();
  modal.querySelector('#updates-close')?.addEventListener('click', close);
  modal.querySelector('#updates-cancel')?.addEventListener('click', close);
  modal.querySelector('.modal-backdrop')?.addEventListener('click', close);

  modal.querySelectorAll('.updates-dl-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const nom = btn.dataset.nom;
      const item = modal.querySelector(`.updates-item[data-nom="${CSS.escape(nom)}"]`);
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner lib-ico-12"></span>`;
      await telechargerNouveauxEpisodes(nom);
      if (item) item.remove();
      if (!modal.querySelectorAll('.updates-item').length) close();
    });
  });

  modal.querySelector('#updates-dl-all')?.addEventListener('click', async () => {
    const btn = modal.querySelector('#updates-dl-all');
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner lib-ico-14"></span> Ajout en cours…`;

    const noms = Object.keys(state.updatesParAnime);
    let okCount = 0;
    for (const nom of noms) {
      try {
        const update = state.updatesParAnime[nom];
        if (!update) continue;
        await api.addToQueue(update.nouveaux_episodes[0], update.nouveaux_episodes);
        okCount += update.nouveaux_count;
        delete state.updatesParAnime[nom];
      } catch(e) {
        console.warn(`Échec ajout ${nom}:`, e);
      }
    }
    toast(`✅ ${okCount} épisode${okCount > 1 ? 's' : ''} ajouté${okCount > 1 ? 's' : ''} à la queue`, 'success');

    document.querySelectorAll('.lib-new-badge').forEach(b => b.remove());
    document.querySelectorAll('.lib-has-updates').forEach(c => c.classList.remove('lib-has-updates'));

    const statEl = document.getElementById('lstat-nouveaux');
    if (statEl) {
      statEl.innerHTML = `<span class="lib-stat-icon">✅</span><span class="lib-stat-val lib-txt-green">0</span><span class="lib-stat-lbl">À jour</span>`;
      statEl.onclick = null;
      statEl.style.cursor = '';
    }
    close();
  });
}
