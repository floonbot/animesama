import { esc } from '../../utils/escape.js';
import { coverSrc } from '../../utils/cover.js';
import { normaliserTexte } from '../../utils/texte.js';
import { _fmtTaille, _isRecent, _qualite, detectLangue, slugify, sortScanEpisodes } from './format.js';
import { _getFavs, _getNames, _getViews } from './storage.js';
import { state } from './state.js';
import { getMissingBadge, getMissingHeader } from './missing.js';

export function renderAllAnimes(animes, favSet) {
  const views = _getViews();
  const names = _getNames();
  const out = [];
  for (const a of animes) {
    out.push(renderAnime(a, favSet, views, names));
  }
  return out.join('');
}

function renderAnime(anime, favSet, views, names) {
  favSet = favSet || _getFavs();
  if (!views) views = _getViews();
  if (!names) names = _getNames();
  const isFav   = favSet.has(anime.nom);
  const languesSet = new Set();
  for (const s of anime.saisons) {
    for (const e of s.episodes) {
      const lang = detectLangue(e.nom);
      if (lang) languesSet.add(lang);
    }
  }
  const langues = [...languesSet];
  const hasScan  = anime.saisons.some(s => s.episodes.some(e => e.scan));
  const hasVideo = anime.saisons.some(s => s.episodes.some(e => !e.scan));

  return `
    <div class="lib-anime${isFav ? ' lib-fav-anime' : ''}" id="lib-${slugify(anime.nom)}"
      data-nom="${esc(normaliserTexte(anime.nom))}" data-size="${anime.total_size}"
      data-eps="${anime.total_eps}" data-fav="${isFav ? '1' : '0'}"
      data-has-scan="${hasScan ? '1' : '0'}" data-has-video="${hasVideo ? '1' : '0'}">
      <div class="lib-header">
        <div class="lib-header-left" data-action="toggle-open" data-nom="${esc(anime.nom)}" tabindex="0" role="button" aria-label="${esc(anime.nom)}">
          ${state.covers[anime.nom]
            ? `<img src="${esc(coverSrc(state.covers[anime.nom]))}" class="lib-cover-thumb" alt="${esc(anime.nom)}" width="44" height="60" loading="lazy" decoding="async">`
            : `<div class="lib-cover-thumb lib-cover-placeholder">🎌</div>`}
          <div class="flex-fill-min">
            <div class="lib-title">${esc(anime.nom)}</div>
            <div class="lib-meta-11">
              <span>${(hasScan && !hasVideo) ? `📖 ${anime.total_eps} chapitre${anime.total_eps > 1 ? 's' : ''}` : `${anime.total_eps} ep`} · ${anime.total_size} GB</span>
              ${hasScan ? `<span class="lib-scan-badge lib-badge-rem-10">📖 SCAN</span>` : ''}
              ${langues.map(l => `<span class="lib-badge-green-10">${esc(l)}</span>`).join('')}
            </div>
          </div>
        </div>
        <div class="lib-ligne-6">
          <button type="button" class="lib-fav-btn${isFav ? ' active' : ''}" data-action="toggle-fav" data-nom="${esc(anime.nom)}" title="${isFav ? 'Retirer des favoris librairie' : 'Ajouter aux favoris librairie'}" aria-label="${isFav ? 'Retirer des favoris librairie' : 'Ajouter aux favoris librairie'}">⭐</button>
          <button type="button" class="lib-open-btn" data-action="open-folder-root" data-nom="${esc(anime.nom)}" title="Ouvrir le dossier" aria-label="Ouvrir le dossier de l'anime">📂</button>
          ${(() => { const badge = getMissingHeader(anime); return badge; })()}
          <span class="lib-count">${anime.total_eps} ep</span>
          <span class="lib-chevron" data-action="toggle-open" data-nom="${esc(anime.nom)}">▼</span>
        </div>
      </div>
      <div class="lib-body">
        ${anime.saisons.map(s => {
          const saisSize = s.episodes.reduce((sum, e) => sum + e.taille, 0);
          return `
          <div class="lib-saison">
            <label class="lib-saison-check-wrap" title="Tout sélectionner" data-stop>
              <input type="checkbox" class="lib-saison-check lib-ep-check" data-saison>
            </label>
            <details class="lib-saison-acc">
              <summary class="lib-saison-header">
                <div class="lib-saison-title">📁 ${esc(s.nom)} · ${s.episodes.length} ep · ${_fmtTaille(saisSize)}${getMissingBadge(s)}</div>
                <span class="lib-saison-chevron" aria-hidden="true">▾</span>
              </summary>
              <div class="lib-eps-grid">
              ${sortScanEpisodes(s.episodes).map(ep => {
                const nomAff   = names[ep.fichier] || ep.nom;
                const viewCnt  = views[ep.fichier] || 0;
                const qual     = _qualite(ep.taille);
                const recent   = _isRecent(ep.mtime);
                const date     = ep.mtime ? new Date(ep.mtime*1000).toLocaleDateString('fr-FR') : '';
                return `
                <div class="lib-ep" data-langue="${esc(detectLangue(ep.nom))}"
                  data-scan="${ep.scan ? '1' : '0'}"
                  data-cle="${esc(normaliserTexte(nomAff))}"
                  data-fichier="${esc(ep.fichier.replace(/\\/g,'\\\\'))}"
                  title="Double-clic pour lire">
                  <input type="checkbox" class="lib-ep-check">
                  <span class="lib-13-fixe">${ep.scan ? '📖' : '🎬'}</span>
                  <div class="flex-fill-min">
                    <div class="lib-ep-nom lib-titre-tronque">${esc(nomAff)}</div>
                    <div class="lib-ep-meta">
                      <span>${_fmtTaille(ep.taille)}</span>
                      ${qual ? `<span data-s="color:${qual.color};font-weight:700;font-size:9px">${qual.label}</span>` : ''}
                      ${recent ? `<span class="lib-badge-green-9">🆕</span>` : ''}
                      ${date ? `<span>${date}</span>` : ''}
                      ${viewCnt > 0 ? `<span>▶ ${viewCnt}×</span>` : ''}
                    </div>
                  </div>
                  <div class="lib-ep-actions">
                    ${ep.scan ? `
                    <button type="button" class="lib-open-btn lib-play-btn" data-action="read-scan" title="Lire" aria-label="Lire le chapitre">📖</button>
                    <button type="button" class="lib-open-btn" data-action="open" title="Ouvrir le dossier" aria-label="Ouvrir le dossier du chapitre">📂</button>
                    <button type="button" class="lib-open-btn lib-del-btn" data-action="delete" title="Supprimer" aria-label="Supprimer le chapitre">🗑</button>
                    ` : `
                    <button type="button" class="lib-open-btn lib-play-btn" data-action="play" title="Lire" aria-label="Lire l'épisode">▶</button>
                    <button type="button" class="lib-open-btn" data-action="copy-path" title="Copier le chemin" aria-label="Copier le chemin de l'épisode">📋</button>
                    <button type="button" class="lib-open-btn" data-action="rename" title="Renommer" aria-label="Renommer l'épisode">✏️</button>
                    <button type="button" class="lib-open-btn" data-action="open" title="Ouvrir le dossier" aria-label="Ouvrir le dossier de l'épisode">📂</button>
                    <button type="button" class="lib-open-btn lib-del-btn" data-action="delete" title="Supprimer" aria-label="Supprimer l'épisode">🗑</button>
                    `}
                  </div>
                </div>`;
              }).join('')}
              </div>
            </details>
          </div>`;
        }).join('')}
        <div class="lib-bulk-bar hidden" id="bulk-${slugify(anime.nom)}">
          <span class="bulk-count">0 sélectionné(s)</span>
          <button class="bulk-del-btn" data-action="bulk-delete">🗑 Supprimer la sélection</button>
          <button class="bulk-cancel-btn" data-action="bulk-cancel">Annuler</button>
        </div>
      </div>
    </div>`;
}
