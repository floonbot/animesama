
import { esc } from '../utils/escape.js';
import { api } from '../api.js';

let _onKey = null;
let _onScroll = null;
let _prevFocus = null;

const WIDTH_KEY = 'scan_reader_width';
const DIR_KEY = 'scan_reader_dir';
const BR_KEY = 'scan_reader_bright';

const BG_IMAGE = '/img/fond-lecteur-scans.png';

function _num(key, def, lo, hi) {
  const v = parseFloat(localStorage.getItem(key));
  return Number.isFinite(v) ? Math.min(Math.max(v, lo), hi) : def;
}
function _save(key, v) { try { localStorage.setItem(key, String(v)); } catch {} }

function scanChapNum(nom) {
  const m = /(\d+(?:\.\d+)?)/.exec(String(nom || ''));
  return m ? parseFloat(m[1]) : 0;
}

export async function openLocalReader(fichier, title, siblings = null) {
  let nb = 0;
  try {
    const r = await api.getScanLocal(fichier);
    nb = r?.pages || 0;
  } catch { nb = 0; }
  if (!nb) { (await import('../components/toast.js')).toast('⚠️ CBZ illisible', 'error'); return; }

  const enc = encodeURIComponent(fichier);
  const pages = Array.from({ length: nb }, (_, i) => `/api/anime/scan-local-img?fichier=${enc}&page=${i}`);

  let onPrev = null, onNext = null, prevLabel = '', nextLabel = '';
  let chapters = null, current = fichier;
  if (Array.isArray(siblings) && siblings.length) {
    const sorted = [...siblings].sort((a, b) => scanChapNum(a.nom) - scanChapNum(b.nom));
    chapters = sorted.map(s => ({ label: s.nom, value: s.fichier }));
    const idx = sorted.findIndex(s => s.fichier === fichier);
    if (idx > 0) { const p = sorted[idx - 1]; onPrev = () => openLocalReader(p.fichier, p.nom, siblings); prevLabel = `◀ ${p.nom}`; }
    if (idx >= 0 && idx < sorted.length - 1) { const n = sorted[idx + 1]; onNext = () => openLocalReader(n.fichier, n.nom, siblings); nextLabel = `${n.nom} ▶`; }
  }
  openReader({
    title: title || 'Scan', pages, onPrev, onNext, prevLabel, nextLabel,
    chapterLabel: title || '', chapters, current,
    onSelect: chapters ? (v) => { const s = siblings.find(x => x.fichier === v); openLocalReader(v, s ? s.nom : title, siblings); } : null,
  });
}

export function openReader({
  title, pages, onPrev = null, onNext = null, prevLabel = '', nextLabel = '',
  onBack = null, chapterLabel = '', chapters = null, current = null, onSelect = null,
}) {
  closeReader();
  _prevFocus = document.activeElement;
  pages = pages || [];
  const width = _num(WIDTH_KEY, 60, 40, 100);
  const bright = _num(BR_KEY, 1, 0.3, 1.5);
  let dir = localStorage.getItem(DIR_KEY) === 'h' ? 'h' : 'v';

  const modal = document.createElement('div');
  modal.id = 'modal-scan-reader';
  modal.className = 'modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', `Lecture — ${title || 'Scan'}`);
  modal.style.cssText =
    'position:fixed;inset:0;z-index:9999;display:flex;flex-direction:column;' +
    'align-items:stretch;justify-content:flex-start;padding:0;max-width:none;background-color:#070c16;' +
    `background-image:linear-gradient(rgba(8,13,24,.59),rgba(5,9,17,.75)),url('${BG_IMAGE}');` +
    'background-size:cover;background-position:center;background-attachment:fixed;' +

    `--rw:${width}%;--br:${bright}`;

  const dropdown = (Array.isArray(chapters) && chapters.length)
    ? `<select id="reader-chap" class="rd-sel">
        ${chapters.map(c => `<option value="${esc(String(c.value))}" ${String(c.value) === String(current) ? 'selected' : ''}>${esc(c.label)}</option>`).join('')}
       </select>` : '';

  const imgs = pages.map((url, i) => `
    <img src="${esc(url)}" alt="Page ${i + 1}" loading="lazy" referrerpolicy="no-referrer">
  `).join('');

  modal.innerHTML = `
    <div class="rd-top">
      <button type="button" class="rd-btn" id="reader-back" aria-label="Retour">← Retour</button>
      <div class="rd-title">${esc(title || 'Lecture')}${chapterLabel ? ` <span>• ${esc(chapterLabel)}</span>` : ''}</div>
      <span id="reader-count" aria-live="polite" aria-atomic="true" data-s="font-size:12px;color:#9fc2ef;min-width:58px;text-align:center">1 / ${pages.length}</span>
      <button type="button" class="rd-btn" id="reader-full" title="Plein écran" aria-label="Plein écran">⛶</button>
      <button type="button" class="rd-btn" id="reader-close" aria-label="Fermer">✕</button>
      <div class="rd-progress" aria-hidden="true"><span class="rd-progress-bar" id="reader-progress"></span></div>
    </div>

    <div class="rd-body">
      <div class="rd-panel left">
        <div class="rd-sec">
          <h4>Sens de défilement</h4>
          <div class="rd-row">
            <button type="button" class="rd-btn" id="reader-dir-v" title="Vertical">↕</button>
            <button type="button" class="rd-btn" id="reader-dir-h" title="Horizontal">↔</button>
          </div>
        </div>
        <div class="rd-sec">
          <h4>Taille des images</h4>
          <div class="rd-row">
            <button type="button" class="rd-btn" id="reader-zoom-out" aria-label="Réduire">A−</button>
            <button type="button" class="rd-btn" id="reader-zoom-in" aria-label="Agrandir">A+</button>
          </div>
        </div>
        <div class="rd-sec">
          <h4>Confort de lecture</h4>
          <button type="button" class="rd-btn" id="reader-full2" data-s="width:100%">⛶ Plein écran</button>
          <input type="range" id="reader-bright" min="0.3" max="1.5" step="0.05" value="${bright}" aria-label="Luminosité">
        </div>
      </div>

      <div id="reader-scroll" class="${dir === 'h' ? 'rd-h' : ''}" tabindex="0" aria-label="Pages du chapitre">
        ${pages.length ? imgs : '<div data-s="color:#9fc2ef;padding:40px">Aucune page.</div>'}
      </div>

      <div class="rd-panel right">
        ${dropdown ? `<div class="rd-sec"><h4>Chapitre</h4>${dropdown}</div>` : ''}
        <div class="rd-sec">
          <div class="rd-row" data-s="width:100%">
            <button type="button" class="rd-nav" id="reader-prev" ${onPrev ? '' : 'disabled'}>‹</button>
            <button type="button" class="rd-nav" id="reader-next" ${onNext ? '' : 'disabled'}>›</button>
          </div>
        </div>
        <div class="rd-sec">
          <button type="button" class="rd-btn" id="reader-top" data-s="width:100%">⤒ Haut</button>
        </div>
      </div>
    </div>`;

  document.body.appendChild(modal);
  const scroll = modal.querySelector('#reader-scroll');
  scroll.scrollTo({ top: 0, left: 0 });
  setTimeout(() => { try { scroll.focus({ preventScroll: true }); } catch {} }, 0);

  const close = () => closeReader();
  modal.querySelector('#reader-close')?.addEventListener('click', close);
  modal.querySelector('#reader-back')?.addEventListener('click', () => {
    close();
    if (onBack) { onBack(); return; }

    document.getElementById('modal-scans')?.remove();
    document.getElementById('modal-netflix-anime')?.remove();
    document.getElementById('modal-anime')?.classList.add('hidden');
  });
  modal.querySelector('#reader-top')?.addEventListener('click', () => scroll.scrollTo({ top: 0, left: 0, behavior: 'smooth' }));

  const applyWidth = (w) => { modal.style.setProperty('--rw', w + '%'); _save(WIDTH_KEY, w); };
  modal.querySelector('#reader-zoom-in')?.addEventListener('click', () => applyWidth(Math.min(_num(WIDTH_KEY, 60, 40, 100) + 10, 100)));
  modal.querySelector('#reader-zoom-out')?.addEventListener('click', () => applyWidth(Math.max(_num(WIDTH_KEY, 60, 40, 100) - 10, 40)));

  modal.querySelector('#reader-bright')?.addEventListener('input', (e) => {
    modal.style.setProperty('--br', e.target.value); _save(BR_KEY, e.target.value);
  });

  const toggleFull = () => { if (!document.fullscreenElement) modal.requestFullscreen?.(); else document.exitFullscreen?.(); };
  modal.querySelector('#reader-full')?.addEventListener('click', toggleFull);
  modal.querySelector('#reader-full2')?.addEventListener('click', toggleFull);

  const dirV = modal.querySelector('#reader-dir-v');
  const dirH = modal.querySelector('#reader-dir-h');
  const setDir = (d) => {
    dir = d; localStorage.setItem(DIR_KEY, d);
    scroll.classList.toggle('rd-h', d === 'h');
    dirV?.classList.toggle('on', d === 'v');
    dirH?.classList.toggle('on', d === 'h');
    scroll.scrollTo({ top: 0, left: 0 });
    updateCounter();
  };
  dirV?.addEventListener('click', () => setDir('v'));
  dirH?.addEventListener('click', () => setDir('h'));

  if (onPrev) modal.querySelector('#reader-prev')?.addEventListener('click', onPrev);
  if (onNext) modal.querySelector('#reader-next')?.addEventListener('click', onNext);
  if (onSelect) modal.querySelector('#reader-chap')?.addEventListener('change', (e) => onSelect(e.target.value));

  const imgEls = [...scroll.querySelectorAll('img')];
  const counter = modal.querySelector('#reader-count');
  function updateCounter() {
    const h = scroll.classList.contains('rd-h');
    const pos = h ? scroll.scrollLeft + scroll.clientWidth * 0.3 : scroll.scrollTop + scroll.clientHeight * 0.3;
    let cur = 1;
    for (let i = 0; i < imgEls.length; i++) {
      const start = h ? imgEls[i].offsetLeft : imgEls[i].offsetTop;
      if (start <= pos) cur = i + 1; else break;
    }
    if (counter) counter.textContent = `${cur} / ${pages.length}`;
    const pb = modal.querySelector('#reader-progress');
    if (pb) pb.style.transform = `scaleX(${pages.length ? cur / pages.length : 0})`;
  }
  let _tick = false;
  _onScroll = () => {
    if (_tick) return;
    _tick = true;
    requestAnimationFrame(() => { _tick = false; updateCounter(); });
  };
  scroll.addEventListener('scroll', _onScroll, { passive: true });

  setDir(dir);

  _onKey = (e) => {
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft' && onPrev) onPrev();
    else if (e.key === 'ArrowRight' && onNext) onNext();
    else if (e.key === 'Home') scroll.scrollTo({ top: 0, left: 0, behavior: 'smooth' });
    else if (e.key === 'End') scroll.scrollTo({ top: scroll.scrollHeight, left: scroll.scrollWidth, behavior: 'smooth' });
  };
  document.addEventListener('keydown', _onKey);
}

function closeReader() {
  if (_onKey) { document.removeEventListener('keydown', _onKey); _onKey = null; }
  _onScroll = null;
  try { if (document.fullscreenElement) document.exitFullscreen?.(); } catch {}
  document.getElementById('modal-scan-reader')?.remove();
  try { _prevFocus?.focus?.(); } catch {}
  _prevFocus = null;
}
