import { esc } from '../../utils/escape.js';
import { coverSrc } from '../../utils/cover.js';
import { api } from '../../api.js';
import { toast } from '../../components/toast.js';
import { _fmtTaille, _qualite, sortScanEpisodes } from './format.js';
import { VIEWS_KEY, _getNames, _getResume, _getViews } from './storage.js';
import { state } from './state.js';
import { getMissingBadge } from './missing.js';
import { confirmSuppression } from './confirm.js';
import { blocSynopsis, chargerSynopsis, remplirSynopsis } from '../../utils/synopsis.js';

export function openNetflixModal(nom) {
  document.getElementById('modal-netflix-anime')?.remove();
  const anime = state.allAnimes.find(a => a.nom === nom);
  if (!anime) return;

  const modal = document.createElement('div');
  modal.id    = 'modal-netflix-anime';
  modal.className = 'modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', anime.nom || 'Anime');
  const views  = _getViews();
  const names  = _getNames();
  const resume = _getResume();

  const allEpsCalc = anime.saisons.flatMap(s => s.episodes);
  const nbTotal    = allEpsCalc.length;
  const nbVus      = allEpsCalc.filter(ep => (views[ep.fichier] || 0) > 0).length;
  const pctVus     = nbTotal ? Math.round(nbVus / nbTotal * 100) : 0;

  let epReprendre = null;
  for (const ep of allEpsCalc) {
    if (resume[ep.fichier] && resume[ep.fichier] > 5) epReprendre = ep;
  }
  if (!epReprendre) epReprendre = allEpsCalc.find(ep => !(views[ep.fichier] > 0)) || allEpsCalc[0];

  modal.innerHTML = `
    <div class="modal-backdrop" data-close></div>
    <div class="modal-box netflix-modal-box">
      <div class="netflix-modal-header" data-s="background-image:url('${esc(coverSrc(state.covers[anime.nom] || ''))}')">
        <div class="netflix-modal-overlay">
          <div class="netflix-modal-title">${esc(anime.nom)}</div>
          <div class="lib-sous-titre-esp">${anime.total_eps} épisodes · ${anime.total_size} GB</div>

          <div class="netflix-progress-wrap">
            <div class="netflix-progress-bar"><div class="netflix-progress-fill" data-s="width:${pctVus}%"></div></div>
            <span class="netflix-progress-lbl">${nbVus}/${nbTotal} vus · ${pctVus}%</span>
          </div>

          <div class="netflix-hero-actions">
            ${epReprendre ? `<button class="btn btn-ram btn-sm" id="netflix-resume">▶ ${nbVus > 0 ? 'Reprendre' : 'Commencer'}</button>` : ''}
            <button class="btn btn-sm netflix-ghost-btn" id="netflix-mark-all">✓ Tout marquer vu</button>
          </div>
        </div>
        <button type="button" class="modal-close lib-coin-hd" data-close aria-label="Fermer">✕</button>
      </div>
      <div class="netflix-modal-body">
        ${blocSynopsis('netflix-synopsis')}
        ${anime.saisons.map(s => `
          <div class="lib-mb-20">
            <div class="lib-saison-title lib-mb-10">📁 ${esc(s.nom)} · ${s.episodes.length} ep${getMissingBadge(s)}</div>
            <div class="lib-col-6">
              ${sortScanEpisodes(s.episodes).map(ep => {
                const nomAff  = names[ep.fichier] || ep.nom;
                const viewCnt = views[ep.fichier] || 0;
                const vu      = viewCnt > 0;
                const enCours = resume[ep.fichier] && resume[ep.fichier] > 5 && !vu;
                const qual    = _qualite(ep.taille);
                return `<div class="lib-ep ${vu ? 'lib-ep-vu' : ''}" data-fichier="${esc(ep.fichier.replace(/\\/g,'\\\\'))}">
                  <span class="lib-13-fixe">${vu ? '✅' : (enCours ? '⏸' : (ep.scan ? '📖' : '🎬'))}</span>
                  <div class="flex-fill-min">
                    <div class="lib-ep-nom lib-titre-tronque">${esc(nomAff)}</div>
                    <div class="lib-meta-10">
                      <span>${_fmtTaille(ep.taille)}</span>
                      ${qual ? `<span data-s="color:${qual.color};font-weight:700;font-size:9px">${qual.label}</span>` : ''}
                      ${vu ? `<span class="lib-c-green">▶ vu ${viewCnt}×</span>` : (enCours ? '<span class="lib-c-amber">⏸ en cours</span>' : '')}
                    </div>
                  </div>
                  <div class="lib-ep-actions">
                    ${ep.scan
                      ? `<button type="button" class="lib-open-btn lib-play-btn" data-action="read-scan" title="Lire" aria-label="Lire le chapitre">📖</button>`
                      : `<button type="button" class="lib-open-btn lib-play-btn" data-action="play" title="Lire" aria-label="Lire l'épisode">▶</button>`}
                    <button type="button" class="lib-open-btn" data-action="open" title="Dossier" aria-label="Ouvrir le dossier">📂</button>
                    <button type="button" class="lib-open-btn lib-del-btn" data-action="delete" title="Supprimer" aria-label="Supprimer">🗑</button>
                  </div>
                </div>`;
              }).join('')}
            </div>
          </div>
        `).join('')}
      </div>
    </div>`;

  document.body.appendChild(modal);
  modal.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', () => modal.remove()));

  // Le nom de dossier suffit : le serveur retrouve la fiche comme « Nouveautes ».
  chargerSynopsis({ nom: anime.nom }).then(t => remplirSynopsis(modal.querySelector('.netflix-synopsis'), t));

  const allEps = anime.saisons.flatMap(s => s.episodes);

  modal.querySelector('#netflix-resume')?.addEventListener('click', async () => {
    if (!epReprendre) return;
    if (epReprendre.scan) {
      const { openLocalReader } = await import('../scan-reader.js');
      const sib = allEps.filter(e => e.scan).map(e => ({ fichier: e.fichier, nom: e.nom }));
      openLocalReader(epReprendre.fichier, epReprendre.nom || 'Scan', sib);
      return;
    }
    const playlist = allEps.map(e => e.fichier);
    window.lireEpisode(epReprendre.fichier, playlist, allEps.findIndex(e => e.fichier === epReprendre.fichier));
  });

  modal.querySelector('#netflix-mark-all')?.addEventListener('click', () => {
    const v = _getViews();
    allEps.forEach(ep => { if (!(v[ep.fichier] > 0)) v[ep.fichier] = 1; });
    try { localStorage.setItem(VIEWS_KEY, JSON.stringify(v)); } catch {}
    toast('✅ Tous les épisodes marqués comme vus', 'success');
    openNetflixModal(nom);
  });

  modal.addEventListener('dblclick', (e) => {
    const ep = e.target.closest('.lib-ep');
    ep?.querySelector('[data-action=play], [data-action=read-scan]')?.click();
  });
  modal.addEventListener('click', async (e) => {
    const btn     = e.target.closest('[data-action]');
    if (!btn) return;
    const ep      = btn.closest('.lib-ep');
    const fichier = ep?.dataset.fichier?.replace(/\\\\/g, '\\');
    if (!fichier) return;
    const action  = btn.dataset.action;
    if (action === 'read-scan') {
      const { openLocalReader } = await import('../scan-reader.js');
      const sib = allEps.filter(e => e.scan).map(e => ({ fichier: e.fichier, nom: e.nom }));
      openLocalReader(fichier, ep.querySelector('.lib-ep-nom')?.textContent || 'Scan', sib);
    }
    if (action === 'play') {
      const playlist = allEps.map(e => e.fichier);
      window.lireEpisode(fichier, playlist, allEps.findIndex(e => e.fichier === fichier));
    }
    if (action === 'open')   await window.ouvrirDossier(fichier);
    if (action === 'delete') {
      if (confirmSuppression(btn)) {
        const r = await api.post('/api/anime/supprimer', { fichier }).catch(() => ({ok:false}));
        if (r.ok) { ep.style.opacity='0'; setTimeout(()=>ep.remove(),300); toast('🗑 Supprimé','info'); }
        else toast('❌ Impossible','error');
      }
    }
  });
}
