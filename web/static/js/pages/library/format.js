import { cleAnime, surlignerJetons } from '../../utils/texte.js';

export function _fmtTaille(mb) {
  if (mb >= 1000) return (mb / 1024).toFixed(2) + ' GB';
  return mb + ' MB';
}

export function _fmtDuree(minutes) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h${m > 0 ? m + 'min' : ''}` : `${m}min`;
}

export function _isRecent(mtime) {
  return mtime && (Date.now() / 1000 - mtime) < 7 * 86400;
}

export function _qualite(mb) {
  if (mb >= 500) return { label: 'HD', color: 'var(--rem2)' };
  if (mb < 200)  return { label: 'SD', color: 'var(--muted)' };
  return null;
}

export function _extractEpNum(nom) {
  const m = nom.match(/S\d{1,3}E(\d{1,4})/i);
  return m ? parseInt(m[1], 10) : null;
}

export function _extractSaisonNum(nom) {
  const m = nom.match(/S(\d{1,3})E/i);
  return m ? parseInt(m[1], 10) : 1;
}

export function highlight(text, jetons) {
  return surlignerJetons(text, jetons, '<mark class="lib-surlignage">', '</mark>');
}

export function detectLangue(nom) {
  if (/vostfr/i.test(nom)) return 'VOSTFR';
  if (/\bvf\b/i.test(nom))  return 'VF';
  if (/vo\b/i.test(nom))    return 'VO';
  return '';
}

export { cleAnime as _normalise };

export function slugify(s) {
  return s.replace(/[^a-z0-9]/gi, '-').toLowerCase();
}

function chapNum(nom) {
  const m = /(\d+(?:\.\d+)?)/.exec(String(nom || ''));
  return m ? parseFloat(m[1]) : 0;
}

export function sortScanEpisodes(episodes) {
  if (!episodes.some(e => e.scan)) return episodes;
  return [...episodes].sort((a, b) => chapNum(a.nom) - chapNum(b.nom));
}
