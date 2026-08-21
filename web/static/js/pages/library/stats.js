import { esc } from '../../utils/escape.js';
import { toast } from '../../components/toast.js';
import { _fmtDuree, _fmtTaille, detectLangue } from './format.js';
import { _getViews } from './storage.js';

export function exportListe(allAnimes) {
  const lines = ['Anime;Saison;Épisode;Taille;Langue'];
  allAnimes.forEach(a => {
    a.saisons.forEach(s => {
      s.episodes.forEach(ep => {
        lines.push(`"${a.nom}";"${s.nom}";"${ep.nom}";"${_fmtTaille(ep.taille)}";"${detectLangue(ep.nom)}"`);
      });
    });
  });
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const a    = document.createElement('a');
  a.href     = URL.createObjectURL(blob);
  a.download = 'librairie.csv';
  a.click();
  toast('📥 Export téléchargé !', 'success');
}

export function showStatsModal(allAnimes) {
  document.getElementById('modal-lib-stats')?.remove();
  const totalEps   = allAnimes.reduce((s, a) => s + a.total_eps, 0);
  const totalGb    = allAnimes.reduce((s, a) => s + a.total_size, 0);
  const plusLourd  = [...allAnimes].sort((a,b) => b.total_size - a.total_size)[0];
  const plusLong   = [...allAnimes].sort((a,b) => b.total_eps - a.total_eps)[0];
  const views      = _getViews();
  const mostViewed = Object.entries(views).sort((a,b) => b[1]-a[1])[0];

  const modal = document.createElement('div');
  modal.id    = 'modal-lib-stats';
  modal.className = 'modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Statistiques librairie');
  modal.innerHTML = `
    <div class="modal-backdrop" data-close></div>
    <div class="modal-box lib-max-480">
      <div class="modal-header">
        <h2 class="modal-title">📊 Statistiques librairie</h2>
        <button class="modal-close" data-close>✕</button>
      </div>
      <div class="lib-col-12">
        <div class="stat-row"><span>Total animes</span><strong>${allAnimes.length}</strong></div>
        <div class="stat-row"><span>Total épisodes</span><strong>${totalEps}</strong></div>
        <div class="stat-row"><span>Durée estimée</span><strong>${_fmtDuree(totalEps * 24)}</strong></div>
        <div class="stat-row"><span>Stockage total</span><strong>${totalGb.toFixed(2)} GB</strong></div>
        ${plusLourd ? `<div class="stat-row"><span>Anime le plus lourd</span><strong>${esc(plusLourd.nom)} (${plusLourd.total_size} GB)</strong></div>` : ''}
        ${plusLong  ? `<div class="stat-row"><span>Anime le plus long</span><strong>${esc(plusLong.nom)} (${plusLong.total_eps} ep)</strong></div>` : ''}
        ${mostViewed ? `<div class="stat-row"><span>Épisode le plus vu</span><strong>${esc(mostViewed[0].split(/[/\\]/).pop())} (${mostViewed[1]}×)</strong></div>` : ''}
      </div>
    </div>`;
  document.body.appendChild(modal);
  modal.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', () => modal.remove()));
}
