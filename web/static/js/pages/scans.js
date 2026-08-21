
import { esc } from '../utils/escape.js';
import { coverSrc } from '../utils/cover.js';
import { api } from '../api.js';
import { toast } from '../components/toast.js';

export { slugFromUrl } from '../utils/slug.js';

const _sel = new Set();
let _info = null;
let _ctx = { slug: '', nom: '', cover: '' };

function _progKey(slug) { return 'scan_prog_' + slug; }
function getScanProgress(slug) { try { return localStorage.getItem(_progKey(slug)) || ''; } catch { return ''; } }
function setScanProgress(slug, num) { try { localStorage.setItem(_progKey(slug), String(num)); } catch {} }

export async function openScansModal(slug, nom, cover = '') {
  slug = slug || '';
  if (!slug) { toast('⚠️ Œuvre inconnue', 'info'); return; }
  _ctx = { slug, nom: nom || slug, cover };

  const coverUrl = cover || `https://raw.githubusercontent.com/Anime-Sama/IMG/img/contenu/${slug}.jpg`;

  document.getElementById('modal-anime')?.classList.add('hidden');
  document.getElementById('modal-netflix-anime')?.remove();

  document.getElementById('modal-scans')?.remove();
  const modal = document.createElement('div');
  modal.id = 'modal-scans';
  modal.className = 'modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', `Scans — ${nom || slug}`);
  modal.innerHTML = `
    <div class="modal-backdrop" data-close></div>
    <div class="modal-box">
      <div class="sc-head">
        <div class="sc-coverbox">
          <span class="sc-cover-ph">📖</span>
          <img class="sc-cover" id="sc-cover-img" alt="" loading="lazy">
        </div>
        <div class="sc-htitle">
          <h2>${esc(nom || slug)}</h2>
          <div class="sc-sub">📖 Scans</div>
        </div>
        <button type="button" class="modal-close sc-close" data-close aria-label="Fermer">✕</button>
      </div>
      <div class="sc-body" id="scans-body">
        <div data-s="text-align:center;padding:40px"><span class="spinner"></span> Chargement des chapitres…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);

  const coverImg = modal.querySelector('#sc-cover-img');
  if (coverImg) {
    coverImg.addEventListener('error', () => coverImg.remove());
    coverImg.src = coverSrc(coverUrl);
  }

  modal.querySelectorAll('[data-close]').forEach(el =>
    el.addEventListener('click', () => modal.remove()));

  await _charger(slug, nom, 'vf');
}

async function _charger(slug, nom, lang) {
  _sel.clear();
  const body = document.getElementById('scans-body');
  if (!body) return;
  body.innerHTML = '<div data-s="text-align:center;padding:40px"><span class="spinner"></span> Chargement…</div>';
  try {
    _info = await api.getScanInfo(slug, lang);
  } catch (e) {
    body.innerHTML = `<div data-s="color:var(--red);padding:24px;text-align:center">❌ ${esc(e.message)}</div>`;
    return;
  }
  if (!_info || !_info.ok || !(_info.chapitres || []).length) {
    body.innerHTML = `<div data-s="color:var(--muted);padding:30px;text-align:center">Aucun scan disponible pour cette œuvre.</div>`;
    return;
  }
  _render(slug, nom);
}

function _render(slug, nom) {
  const body = document.getElementById('scans-body');
  if (!body) return;
  const { chapitres, lang, oeuvre } = _info;

  const saved = getScanProgress(_ctx.slug);
  const resumeNum = (saved && chapitres.some(c => String(c.num) === saved))
    ? saved : (chapitres[0] ? chapitres[0].num : '1');

  const chips = chapitres.map(c => `
    <button type="button" class="scan-chip" data-num="${esc(c.num)}"
      title="${c.pages ? esc(String(c.pages)) + ' page(s)' : ''}">${esc(c.num)}</button>`).join('');

  body.innerHTML = `
    <div class="sc-sec">▶ Lecture</div>
    <div data-s="display:flex;flex-wrap:wrap;gap:10px;align-items:center">
      <button type="button" class="btn btn-ram" id="scan-resume">▶ ${saved ? 'Reprendre' : 'Commencer'} — Ch. ${esc(String(resumeNum))}</button>
      <span data-s="font-size:12px;color:var(--muted)">ou aller au</span>
      <input id="scan-read-num" class="sc-input" type="text" inputmode="numeric" placeholder="n° chapitre" data-s="width:104px">
      <button type="button" class="btn btn-sm sc-tool" id="scan-read">Aller</button>
    </div>

    <div class="sc-divider"></div>

    <div class="sc-sec">⬇️ Télécharger — sélectionne des chapitres</div>
    <div data-s="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px">
      <button type="button" class="btn btn-sm sc-tool" id="scan-all">Tout</button>
      <button type="button" class="btn btn-sm sc-tool" id="scan-none">Aucun</button>
      <span data-s="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);margin-left:4px">
        Plage
        <input id="scan-from" class="sc-input" type="number" inputmode="numeric" placeholder="de" data-s="width:66px">
        <input id="scan-to" class="sc-input" type="number" inputmode="numeric" placeholder="à" data-s="width:66px">
        <button type="button" class="btn btn-sm sc-tool" id="scan-range">OK</button>
      </span>
    </div>
    <div id="scan-grid" class="sc-grid">${chips}</div>

    <div data-s="display:flex;align-items:center;gap:12px;margin-top:16px;padding-top:14px;border-top:1px solid var(--border2)">
      <span id="scan-count" data-s="font-size:13px;color:var(--muted)">0 chapitre(s) sélectionné(s)</span>
      <button type="button" class="btn btn-ram" id="scan-dl" data-s="margin-left:auto" disabled>⬇️ Télécharger</button>
    </div>`;

  const grid = document.getElementById('scan-grid');
  grid.addEventListener('click', (e) => {
    const chip = e.target.closest('.scan-chip');
    if (!chip) return;
    _toggle(chip, !chip.classList.contains('scan-chip-on'));
    _refreshCount();
  });

  document.getElementById('scan-all')?.addEventListener('click', () => {
    grid.querySelectorAll('.scan-chip').forEach(ch => _toggle(ch, true));
    _refreshCount();
  });
  document.getElementById('scan-none')?.addEventListener('click', () => {
    grid.querySelectorAll('.scan-chip').forEach(ch => _toggle(ch, false));
    _refreshCount();
  });
  document.getElementById('scan-range')?.addEventListener('click', () => {
    const from = parseFloat(document.getElementById('scan-from').value);
    const to   = parseFloat(document.getElementById('scan-to').value);
    if (Number.isNaN(from) || Number.isNaN(to)) { toast('⚠️ Plage invalide', 'info'); return; }
    const lo = Math.min(from, to), hi = Math.max(from, to);
    grid.querySelectorAll('.scan-chip').forEach(ch => {
      const n = parseFloat(ch.dataset.num);
      if (!Number.isNaN(n) && n >= lo && n <= hi) _toggle(ch, true);
    });
    _refreshCount();
  });

  const _doRead = () => {
    const v = (document.getElementById('scan-read-num').value || '').trim();
    if (!v) { toast('⚠️ Entre un numéro de chapitre', 'info'); return; }
    _lireChapitre(v);
  };
  document.getElementById('scan-resume')?.addEventListener('click', () => _lireChapitre(resumeNum));
  document.getElementById('scan-read')?.addEventListener('click', _doRead);
  document.getElementById('scan-read-num')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') _doRead();
  });

  document.getElementById('scan-dl')?.addEventListener('click', async () => {
    const chapitres = [..._sel];
    if (!chapitres.length) { toast('⚠️ Sélectionne au moins un chapitre', 'info'); return; }
    const btn = document.getElementById('scan-dl');
    if (btn.disabled) return;
    btn.disabled = true;
    try {
      const r = await api.addScanToQueue({ slug, oeuvre, lang, chapitres, nom: nom || oeuvre });
      if (r.ok) {
        toast(`✅ ${chapitres.length} chapitre(s) ajouté(s) à la file`, 'success');
        document.getElementById('modal-scans')?.remove();
      } else {
        toast(`❌ ${r.message || 'Erreur'}`, 'error');
        btn.disabled = false;
      }
    } catch (e) {
      toast(`❌ ${e.message}`, 'error');
      btn.disabled = false;
    }
  });
}

function _toggle(chip, on) {
  const num = chip.dataset.num;
  chip.classList.toggle('scan-chip-on', on);
  if (on) _sel.add(num); else _sel.delete(num);
}

function _refreshCount() {
  const c = document.getElementById('scan-count');
  if (c) c.textContent = `${_sel.size} chapitre(s) sélectionné(s)`;
  const btn = document.getElementById('scan-dl');
  if (btn) btn.disabled = _sel.size === 0;
}

async function _lireChapitre(num) {
  if (!_info) return;
  const { oeuvre, lang, chapitres } = _info;
  const nums = chapitres.map(c => String(c.num));
  const idx = nums.indexOf(String(num).trim());
  if (idx === -1) { toast('⚠️ Chapitre introuvable', 'info'); return; }
  const cur = nums[idx];
  setScanProgress(_ctx.slug, cur);

  let pages = [];
  try {
    const r = await api.getScanPages(oeuvre, cur, lang);
    pages = (r.pages || []).map(p => p.url).filter(Boolean);
  } catch (e) { toast(`❌ ${e.message}`, 'error'); return; }
  if (!pages.length) { toast('⚠️ Aucune page pour ce chapitre', 'info'); return; }

  const { openReader } = await import('./scan-reader.js');
  openReader({
    title: _ctx.nom || oeuvre,
    chapterLabel: `Chapitre ${cur} (${String(lang).toUpperCase()})`,
    pages,
    chapters: chapitres.map(c => ({ label: 'Chapitre ' + c.num, value: String(c.num) })),
    current: cur,
    onSelect: (v) => _lireChapitre(v),
    prevLabel: idx > 0 ? `◀ Ch. ${nums[idx - 1]}` : '',
    nextLabel: idx < nums.length - 1 ? `Ch. ${nums[idx + 1]} ▶` : '',
    onPrev: idx > 0 ? () => _lireChapitre(nums[idx - 1]) : null,
    onNext: idx < nums.length - 1 ? () => _lireChapitre(nums[idx + 1]) : null,
  });
}
