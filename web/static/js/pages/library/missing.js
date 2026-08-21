import { _extractEpNum, _extractSaisonNum } from './format.js';

export async function detectMissingEps(animes) {
  const statEl = document.getElementById('lstat-ep-manquants');
  if (!statEl) return;
  let totalManquants = 0;
  for (const anime of animes) {
    for (const saison of anime.saisons) {
      const eps = saison.episodes.map(e => ({
        num: _extractEpNum(e.nom),
        s:   _extractSaisonNum(e.nom),
      })).filter(e => e.num !== null);
      const groupes = {};
      for (const e of eps) { (groupes[e.s] = groupes[e.s] || []).push(e.num); }
      for (const nums of Object.values(groupes)) {
        if (nums.length < 2) continue;
        const min = Math.min(...nums), max = Math.max(...nums);
        for (let i = min; i <= max; i++) { if (!nums.includes(i)) totalManquants++; }
      }
    }
  }
  if (!totalManquants) {
    statEl.innerHTML = `<span class="lib-stat-icon">✅</span><span class="lib-stat-val lib-txt-green">0</span><span class="lib-stat-lbl">Manquants</span>`;
  } else {
    statEl.innerHTML = `<span class="lib-stat-icon">⚠️</span><span class="lib-stat-val lib-txt-yellow">${totalManquants}</span><span class="lib-stat-lbl">Manquants</span>`;
    statEl.style.cursor = 'pointer';
    statEl.title = 'Épisodes manquants dans la numérotation locale';
  }
}

export function getMissingHeader(anime) {
  let total = 0;
  for (const saison of anime.saisons) {
    const eps = saison.episodes.map(e => ({ num: _extractEpNum(e.nom), s: _extractSaisonNum(e.nom) })).filter(e => e.num !== null);
    const groupes = {};
    for (const e of eps) { (groupes[e.s] = groupes[e.s] || []).push(e.num); }
    for (const nums of Object.values(groupes)) {
      if (nums.length < 2) continue;
      const min = Math.min(...nums), max = Math.max(...nums);
      for (let i = min; i <= max; i++) { if (!nums.includes(i)) total++; }
    }
  }
  return total ? `<span class="lib-missing-header">⚠️ ${total}</span>` : '';
}

export function getMissingBadge(saison) {
  const eps = saison.episodes.map(e => ({ num: _extractEpNum(e.nom), s: _extractSaisonNum(e.nom) })).filter(e => e.num !== null);
  const groupes = {};
  for (const e of eps) { (groupes[e.s] = groupes[e.s] || []).push(e.num); }
  const manquants = [];
  for (const nums of Object.values(groupes)) {
    if (nums.length < 2) continue;
    const min = Math.min(...nums), max = Math.max(...nums);
    for (let i = min; i <= max; i++) { if (!nums.includes(i)) manquants.push(i); }
  }
  if (!manquants.length) return '';
  const nb = manquants.length;
  return `<span class="lib-missing-badge">⚠️ ${nb} manquant${nb>1?'s':''} (ep ${manquants.slice(0,8).join(', ')}${nb>8?'…':''})</span>`;
}
