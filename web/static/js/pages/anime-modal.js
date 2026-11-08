import { esc } from '../utils/escape.js';
import { coverSrc } from '../utils/cover.js';
import { etiquetteSaison } from '../utils/etiquette.js';
import { blocSynopsis, chargerSynopsis, remplirSynopsis } from '../utils/synopsis.js';
import { api }   from '../api.js';
import { toast } from '../components/toast.js';

function _heroSkeleton(anime) {
  return `
    <div class="anime-hero">
      ${anime.image ? `<div class="anime-hero-bg" data-s="background-image:url('${esc(coverSrc(anime.image))}')"></div>` : ''}
      <div class="anime-hero-content">
        ${anime.image
          ? `<img src="${esc(coverSrc(anime.image))}" class="anime-hero-cover" alt="${esc(anime.nom)}">`
          : `<div class="anime-hero-cover anime-hero-cover-ph">🎌</div>`}
        <div class="anime-hero-info">
          <h2 class="anime-hero-title">${esc(anime.nom || '')}</h2>
          <div class="anime-hero-meta">
            ${anime.statut ? `<span class="anime-chip anime-chip-green">${esc(anime.statut)}</span>` : ''}
          </div>
          ${blocSynopsis('anime-synopsis')}
        </div>
      </div>
    </div>
    <div data-s="text-align:center;padding:30px"><span class="spinner"></span> Chargement des épisodes…</div>`;
}

export async function loadAnimeModal(anime) {
  const content = document.getElementById('modal-anime-content');
  content.innerHTML = _heroSkeleton(anime);
  // Une requete a part, jamais attendue par les episodes ; remplie dans le
  // squelette, puis de nouveau dans la fiche rendue qui le remplace.
  const synopsis = chargerSynopsis({ url: anime.url });
  const _remplir = () => synopsis.then(t => remplirSynopsis(content.querySelector('.anime-synopsis'), t));
  _remplir();
  try {
    // La langue par defaut ne conditionne pas la requete d'episodes : les
    // enchainer coutait un aller-retour complet avant de commencer le vrai.
    const [reglages, episodes] = await Promise.all([
      api.getCached('/api/settings', 30000).catch(() => null),
      api.getEpisodes(anime.url),
    ]);
    const brut = reglages?.langue_defaut;
    renderAnimeModal(anime, episodes, brut ? String(brut).toUpperCase() : 'VOSTFR');
    _remplir();
  } catch(e) {
    content.innerHTML = `<div data-s="color:var(--red);padding:20px">❌ ${esc(e.message)}</div>`;
  }
}

function renderAnimeModal(anime, data, langueDefaut = 'VOSTFR') {
  _saisonsOuvertes = null;
  const { titre, episodes = [], langues = [], total } = data;
  const content = document.getElementById('modal-anime-content');

  const parLangue = {};
  for (const ep of episodes) {
    const l = ep.langue || "Sans langue";
    if (!parLangue[l]) parLangue[l] = [];
    parLangue[l].push(ep);
  }

  const languesDispos = Object.keys(parLangue);
  const langueActive  = languesDispos.find(l => l.toUpperCase() === langueDefaut)
                      || languesDispos[0] || "";

  content.innerHTML = `

    <div class="anime-hero">
      ${anime.image ? `<div class="anime-hero-bg" data-s="background-image:url('${esc(coverSrc(anime.image))}')"></div>` : ''}
      <div class="anime-hero-content">
        ${anime.image
          ? `<img src="${esc(coverSrc(anime.image))}" class="anime-hero-cover" alt="${esc(anime.nom)}">`
          : `<div class="anime-hero-cover anime-hero-cover-ph">🎌</div>`}
        <div class="anime-hero-info">
          <h2 class="anime-hero-title">${esc(titre || anime.nom)}</h2>
          <div class="anime-hero-meta">
            ${anime.statut ? `<span class="anime-chip anime-chip-green">${esc(anime.statut)}</span>` : ''}
            ${episodes.length ? `<span class="anime-chip">${total} épisode${total > 1 ? 's' : ''}</span>` : ''}
            ${languesDispos.map(l => `<span class="anime-chip anime-chip-soft">${esc(l)}</span>`).join('')}
          </div>
          ${blocSynopsis('anime-synopsis')}
          <div class="anime-hero-actions" id="dl-all-btns">
            ${languesDispos.map(l => `
              <button class="btn btn-ram btn-sm" id="btn-all-${l.replace(/\s/g,'_')}">
                ⬇️ Tout en ${l}
              </button>
            `).join('')}
            ${episodes.length ? `
            <button class="btn btn-sm" id="btn-select-mode"
              data-s="background:var(--bg3);color:var(--muted);border:1px solid var(--border2)">
              ☑️ Sélection
            </button>` : ''}
          </div>
        </div>
      </div>
    </div>

    ${languesDispos.length > 1 ? `
    <div data-s="display:flex;gap:6px;margin-bottom:12px;margin-top:4px" id="tabs">
      ${languesDispos.map((l,i) => `
        <button id="tab-${l.replace(/\s/g,'_')}"
          data-s="padding:6px 14px;border-radius:20px;font-size:12px;font-weight:700;cursor:pointer;border:none;font-family:inherit;transition:all .2s;
                 background:${l===langueActive?'linear-gradient(135deg,var(--rem),var(--ram))':'var(--bg3)'};
                 color:${l===langueActive?'#fff':'var(--muted)'}">
          ${esc(l)} (${parLangue[l].length})
        </button>
      `).join('')}
    </div>` : ''}

    <div id="select-bar" data-s="display:none;align-items:center;gap:8px;margin-bottom:10px;
      padding:8px 12px;background:var(--bg3);border-radius:8px;border:1px solid var(--border2)">
      <button class="btn btn-sm" id="btn-sel-all" data-s="background:var(--bg2);font-size:11px">Tout sélectionner</button>
      <button class="btn btn-sm" id="btn-sel-none" data-s="background:var(--bg2);font-size:11px">Tout désélectionner</button>
      <span id="sel-count" data-s="font-size:11px;color:var(--muted);margin-left:4px">0 sélectionné(s)</span>
      <button class="btn btn-ram btn-sm" id="btn-dl-sel" data-s="margin-left:auto" disabled>⬇️ Télécharger la sélection</button>
    </div>

    <div id="ep-grid">
      ${renderGrid(parLangue[langueActive] || episodes, false)}
    </div>`;

  let selectMode = false;
  let langueEnCours = langueActive;

  document.getElementById('btn-select-mode')?.addEventListener('click', () => {
    selectMode = !selectMode;
    const btn = document.getElementById('btn-select-mode');
    const bar = document.getElementById('select-bar');
    btn.style.background = selectMode ? 'var(--rem)' : 'var(--bg3)';
    btn.style.color      = selectMode ? '#fff' : 'var(--muted)';
    bar.style.display    = selectMode ? 'flex' : 'none';
    document.getElementById('ep-grid').innerHTML = renderGrid(parLangue[langueEnCours] || episodes, selectMode);
    bindEpClicks(parLangue[langueEnCours] || episodes, selectMode);
    bindPagination(parLangue[langueEnCours] || episodes, selectMode);
    updateSelCount();
  });

  document.getElementById('btn-sel-all')?.addEventListener('click', () => {
    document.querySelectorAll('.ep-checkbox').forEach(cb => { cb.checked = true; });
    updateSelCount();
  });

  document.getElementById('btn-sel-none')?.addEventListener('click', () => {
    document.querySelectorAll('.ep-checkbox').forEach(cb => { cb.checked = false; });
    updateSelCount();
  });

  document.getElementById('btn-dl-sel')?.addEventListener('click', async () => {
    const eps = parLangue[langueEnCours] || episodes;
    const selected = [...document.querySelectorAll('.ep-checkbox:checked')].map(cb => eps[parseInt(cb.dataset.idx)]).filter(Boolean);
    if (!selected.length) {
      toast('⚠️ Sélectionne au moins un épisode', 'info');
      return;
    }
    const btn = document.getElementById('btn-dl-sel');
    if (btn?.disabled) return;
    if (btn) { btn.disabled = true; }
    try {
      await api.addToQueue(selected[0], selected);
      toast(`✅ ${selected.length} épisode(s) ajoutés à la queue`, 'success');
      document.getElementById('modal-anime').classList.add('hidden');
    } catch(e) { toast(`❌ ${e.message}`, 'error'); }
    finally    { if (btn) btn.disabled = false; }
  });

  languesDispos.forEach(l => {
    document.getElementById(`btn-all-${l.replace(/\s/g,'_')}`)
      ?.addEventListener('click', async () => {
        const eps = parLangue[l];
        try {
          await api.addToQueue(eps[0], eps);
          toast(`✅ ${eps.length} épisodes ${l} ajoutés à la queue`, 'success');
          document.getElementById('modal-anime').classList.add('hidden');
        } catch(e) { toast(`❌ ${e.message}`, 'error'); }
      });
  });

  languesDispos.forEach((l, i) => {
    document.getElementById(`tab-${l.replace(/\s/g,'_')}`)
      ?.addEventListener('click', () => {
        langueEnCours = l;
        languesDispos.forEach(ll => {
          const t = document.getElementById(`tab-${ll.replace(/\s/g,'_')}`);
          if (t) { t.style.background='var(--bg3)'; t.style.color='var(--muted)'; }
        });
        const tab = document.getElementById(`tab-${l.replace(/\s/g,'_')}`);
        if (tab) { tab.style.background='linear-gradient(135deg,var(--rem),var(--ram))'; tab.style.color='#fff'; }
        document.getElementById('ep-grid').innerHTML = renderGrid(parLangue[l] || [], selectMode);
        bindEpClicks(parLangue[l] || [], selectMode);
        bindPagination(parLangue[l] || [], selectMode);
        updateSelCount();
      });
  });

  bindEpClicks(parLangue[langueActive] || episodes, false);
  bindPagination(parLangue[langueActive] || episodes, false);

  if (!episodes.length) {
    const grid = document.getElementById('ep-grid');
    if (grid) {
      grid.innerHTML = `
        <div data-s="text-align:center;padding:30px;color:var(--muted)">
          Pas d'épisode vidéo pour cette œuvre.
          <div data-s="margin-top:14px">
            <button class="btn btn-ram" id="btn-scans-cta">📖 Voir les scans</button>
          </div>
        </div>`;
      document.getElementById('btn-scans-cta')?.addEventListener('click', async () => {
        const { openScansModal, slugFromUrl } = await import('./scans.js');
        openScansModal(slugFromUrl(anime.url), titre || anime.nom, anime.image);
      });
    }
  }
}

function bindPagination(eps, selectMode) {
  document.querySelectorAll('.season-accordion').forEach(det => {
    det.addEventListener('toggle', () => {
      const s = Number(det.dataset.saison);
      if (Number.isNaN(s) || _saisonsOuvertes === null) return;
      if (det.open) _saisonsOuvertes.add(s);
      else          _saisonsOuvertes.delete(s);
    });
  });
}

let _saisonsOuvertes = null;

function renderGrid(eps, selectMode) {
  if (!eps.length) return '<div data-s="color:var(--muted);padding:20px;text-align:center">Aucun épisode</div>';

  const parSaison = {};
  eps.forEach((ep, idx) => {
    const s = ep.saison ?? 1;
    if (!parSaison[s]) parSaison[s] = [];
    parSaison[s].push({ ep, realIdx: idx });
  });
  const saisons = Object.keys(parSaison).map(Number).sort((a,b) => a-b);

  if (_saisonsOuvertes === null) _saisonsOuvertes = new Set();

  const accordions = saisons.map((s) => {
    const items = parSaison[s];
    const label = etiquetteSaison(items[0] && items[0].ep);
    const cards = items.map(({ ep, realIdx }) => `
      <div class="ep-chip ${selectMode ? 'ep-chip-select' : ''}" data-idx="${realIdx}">
        ${selectMode ? `<input type="checkbox" class="ep-checkbox" data-idx="${realIdx}" />` : ''}
        <div class="ep-num">Ép. ${esc(String(ep.episode))}</div>
        ${ep.langue ? `<div class="ep-lang">${esc(ep.langue)}</div>` : ''}
      </div>`).join('');

    const estOuverte = _saisonsOuvertes.has(s);
    return `
      <details class="season-accordion" data-saison="${s}" ${estOuverte ? 'open' : ''}>
        <summary class="season-summary">
          <span class="season-label">${esc(label)}</span>
          <span class="season-count">${items.length} ép.</span>
          <span class="season-chevron">▾</span>
        </summary>
        <div class="ep-grid season-grid">${cards}</div>
      </details>`;
  }).join('');

  return `<div class="seasons-accordion-wrap">${accordions}</div>`;
}

function updateSelCount() {
  const n = document.querySelectorAll('.ep-checkbox:checked').length;
  const countEl = document.getElementById('sel-count');
  const dlBtn   = document.getElementById('btn-dl-sel');
  if (countEl) countEl.textContent = `${n} sélectionné(s)`;
  if (dlBtn)   dlBtn.disabled = n === 0;
}

function bindEpClicks(eps, selectMode) {
  document.querySelectorAll('.ep-chip').forEach(card => {
    card.onmouseenter = () => { card.style.borderColor='var(--rem)'; card.style.background='rgba(74,143,232,.12)'; };
    card.onmouseleave = () => { card.style.borderColor='var(--border2)'; card.style.background='var(--bg3)'; };

    if (selectMode) {
      card.addEventListener('click', (e) => {
        if (e.target.type === 'checkbox') return;
        const cb = card.querySelector('.ep-checkbox');
        if (cb) { cb.checked = !cb.checked; updateSelCount(); }
      });
      card.querySelector('.ep-checkbox')?.addEventListener('change', updateSelCount);
    } else {
      card.addEventListener('click', async () => {
        if (card.dataset.adding === '1') return;
        const ep = eps[parseInt(card.dataset.idx)];
        if (!ep) return;
        card.dataset.adding = '1';
        card.style.borderColor = 'var(--green)';
        card.style.background  = 'rgba(74,232,160,.1)';
        try {
          await api.addToQueue(ep, [ep]);
          toast(`✅ Ép. ${ep.episode} ${ep.langue||''} ajouté`, 'success');
        } catch(e) {
          toast(`❌ ${e.message}`, 'error');
          card.style.borderColor = 'var(--red)';
        } finally {
          setTimeout(() => { card.dataset.adding = ''; }, 1000);
        }
      });
    }
  });
}
