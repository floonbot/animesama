import { esc } from '../../utils/escape.js';
import { api } from '../../api.js';
import { toast } from '../../components/toast.js';

// Ordre d'affichage, et ce qui est coche d'office : supprimer un episode
// tronque oblige a le retelecharger, c'est a l'utilisateur de le decider.
const GROUPES = [
  { type: 'ts',      titre: '🎞️ Illisibles dans l\'app — conversion en MP4', coche: true,
    aide: 'Flux MPEG-TS bruts : le lecteur intégré ne les ouvre pas. Conversion sans perte, la vidéo est seulement ré-emballée.' },
  { type: 'mux',     titre: '✏️ Épisodes complets jamais renommés', coche: true,
    aide: 'Le mux a réussi mais le fichier a gardé son nom provisoire .MUX.' },
  { type: 'residu',  titre: '🧹 Restes de téléchargements', coche: true,
    aide: 'Fichiers intermédiaires ou doublons que rien ne lit.' },
  { type: 'tronque', titre: '✂️ Fichiers tronqués', coche: false,
    aide: 'La fin de la vidéo manque. Les supprimer permet de les retélécharger depuis « Incomplets » ou « Nouveautés ».' },
];

const _POLL_MS = 1500;
let _poll = null;

function _taille(octets) {
  if (octets >= 1024 ** 3) return `${(octets / 1024 ** 3).toFixed(1)} Go`;
  if (octets >= 1024 ** 2) return `${Math.round(octets / 1024 ** 2)} Mo`;
  return `${Math.max(1, Math.round(octets / 1024))} Ko`;
}

function _fermer(modal) {
  clearTimeout(_poll);
  _poll = null;
  modal.remove();
}

function _corps(modal) {
  return modal.querySelector('.sante-corps');
}

function _actions(modal) {
  return modal.querySelector('.modal-actions');
}

export async function ouvrirSante(onRepare) {
  document.getElementById('modal-sante')?.remove();
  const wrapper = document.createElement('div');
  wrapper.innerHTML = `
    <div class="modal" id="modal-sante" role="dialog" aria-modal="true" aria-label="Santé de la librairie">
      <div class="modal-backdrop"></div>
      <div class="modal-box modal-wide">
        <button class="modal-close" aria-label="Fermer" type="button">✕</button>
        <h2>🩺 Santé de la librairie</h2>
        <div class="sante-corps"><p class="lib-intro"><span class="spinner"></span> Analyse des fichiers…</p></div>
        <div class="modal-actions"></div>
      </div>
    </div>`;
  const modal = wrapper.firstElementChild;
  document.body.appendChild(modal);
  modal.querySelector('.modal-close').addEventListener('click', () => _fermer(modal));
  modal.querySelector('.modal-backdrop').addEventListener('click', () => _fermer(modal));

  try {
    const etat = await api.get('/api/anime/sante-librairie/etat');
    if (etat?.en_cours) { _suivre(modal, onRepare); return; }
    const r = await api.get('/api/anime/sante-librairie', { timeout: 0 });
    if (!modal.isConnected) return;
    if (r?.erreur) throw new Error('analyse impossible');
    _afficherAnalyse(modal, r, onRepare);
  } catch (e) {
    if (modal.isConnected) _corps(modal).innerHTML = `<p class="lib-intro">❌ ${esc(e.message)}</p>`;
  }
}

function _afficherAnalyse(modal, r, onRepare) {
  const problemes = r.problemes || [];
  const corps = _corps(modal);
  if (!problemes.length) {
    corps.innerHTML = `<p class="lib-intro">✅ Aucun problème sur ${r.fichiers} fichier${r.fichiers > 1 ? 's' : ''}
      <span class="lib-txt-muted-13">(${r.duree_s} s)</span>.</p>`;
    _actions(modal).innerHTML = '<button class="btn btn-ghost" type="button" data-fermer>Fermer</button>';
    _actions(modal).querySelector('[data-fermer]').addEventListener('click', () => _fermer(modal));
    return;
  }

  const groupes = GROUPES
    .map(g => ({ ...g, items: problemes.filter(p => p.type === g.type) }))
    .filter(g => g.items.length);

  corps.innerHTML = `
    <p class="lib-intro">${problemes.length} fichier${problemes.length > 1 ? 's' : ''} à traiter sur ${r.fichiers}
      <span class="lib-txt-muted-13">(${r.duree_s} s). Chaque fichier est revérifié juste avant d'être touché ;
      ceux modifiés depuis moins d'une heure sont laissés de côté.</span></p>
    <div class="sante-liste">
      ${groupes.map(g => `
        <details class="sante-groupe" data-type="${g.type}">
          <summary class="sante-groupe-tete">
            <input type="checkbox" class="sante-groupe-case" aria-label="Tout le groupe" ${g.coche ? 'checked' : ''}>
            <span class="sante-groupe-titre">${g.titre}</span>
            <span class="sante-groupe-compte">${g.items.length} · ${_taille(g.items.reduce((s, p) => s + p.taille, 0))}</span>
          </summary>
          <p class="sante-aide">${esc(g.aide)}</p>
          <ul class="sante-items">
            ${g.items.map(p => `
              <li><label class="sante-item">
                <input type="checkbox" class="sante-case" value="${esc(p.chemin)}" ${g.coche ? 'checked' : ''}>
                <span class="sante-item-nom">${esc(p.anime)} · ${esc(p.saison)} · ${esc(p.fichier)}</span>
                <span class="sante-item-taille">${_taille(p.taille)}</span>
              </label></li>`).join('')}
          </ul>
        </details>`).join('')}
    </div>`;

  const actions = _actions(modal);
  actions.innerHTML = `
    <button class="btn btn-ghost" type="button" data-fermer>Fermer</button>
    <button class="btn btn-ram" type="button" data-reparer></button>`;
  actions.querySelector('[data-fermer]').addEventListener('click', () => _fermer(modal));
  const btn = actions.querySelector('[data-reparer]');

  const coches = () => [...corps.querySelectorAll('.sante-case:checked')].map(c => c.value);
  const maj = () => {
    const n = coches().length;
    btn.textContent = `🔧 Réparer la sélection (${n})`;
    btn.disabled = !n;
    corps.querySelectorAll('.sante-groupe').forEach(g => {
      const cases = [...g.querySelectorAll('.sante-case')];
      const tete = g.querySelector('.sante-groupe-case');
      const nb = cases.filter(c => c.checked).length;
      tete.checked = nb === cases.length;
      tete.indeterminate = nb > 0 && nb < cases.length;
    });
  };
  corps.addEventListener('change', (e) => {
    if (e.target.classList.contains('sante-groupe-case')) {
      e.target.closest('.sante-groupe').querySelectorAll('.sante-case')
        .forEach(c => { c.checked = e.target.checked; });
    }
    maj();
  });
  maj();

  btn.addEventListener('click', async () => {
    const chemins = coches();
    if (!chemins.length) return;
    btn.disabled = true;
    try {
      const r2 = await api.post('/api/anime/sante-librairie/reparer', { chemins });
      if (!r2?.ok) throw new Error(r2?.message || 'refusé');
      _suivre(modal, onRepare);
    } catch (e) {
      toast(`Réparation impossible : ${e.message}`, 'error');
      btn.disabled = false;
    }
  });
}

function _suivre(modal, onRepare) {
  const corps = _corps(modal);
  corps.innerHTML = `
    <p class="lib-intro sante-courant">Réparation en cours…</p>
    <div class="netflix-progress-wrap">
      <div class="netflix-progress-bar"><div class="netflix-progress-fill sante-avance"></div></div>
      <span class="netflix-progress-lbl sante-compte">0/0</span>
    </div>
    <p class="lib-txt-muted-13">Tu peux fermer cette fenêtre : la réparation continue et reprend ici à la réouverture.</p>`;
  const actions = _actions(modal);
  actions.innerHTML = `
    <button class="btn btn-ghost" type="button" data-fermer>Fermer</button>
    <button class="btn btn-ghost" type="button" data-annuler>⏹ Annuler</button>`;
  actions.querySelector('[data-fermer]').addEventListener('click', () => _fermer(modal));
  actions.querySelector('[data-annuler]').addEventListener('click', async (e) => {
    e.currentTarget.disabled = true;
    try { await api.post('/api/anime/sante-librairie/annuler'); } catch {}
  });

  const tour = async () => {
    if (!modal.isConnected) return;
    let e;
    try { e = await api.get('/api/anime/sante-librairie/etat'); } catch { e = null; }
    if (!modal.isConnected) return;
    if (e) {
      const pct = e.total ? Math.round(e.faits / e.total * 100) : 0;
      corps.querySelector('.sante-avance').style.width = `${pct}%`;
      corps.querySelector('.sante-compte').textContent = `${e.faits}/${e.total}`;
      corps.querySelector('.sante-courant').textContent = e.courant
        ? `En cours : ${e.courant}` : 'Réparation en cours…';
      if (!e.en_cours) { _bilan(modal, e, onRepare); return; }
    }
    _poll = setTimeout(tour, _POLL_MS);
  };
  tour();
}

function _bilan(modal, e, onRepare) {
  const echecs = e.echecs || [];
  _corps(modal).innerHTML = `
    <p class="lib-intro">${e.annule ? '⏹ Réparation annulée' : '✅ Réparation terminée'} :
      ${e.reussis}/${e.total} fichier${e.total > 1 ? 's' : ''} traité${e.reussis > 1 ? 's' : ''}.</p>
    ${echecs.length ? `
      <p class="lib-txt-muted-13">${echecs.length} échec${echecs.length > 1 ? 's' : ''} — fichier${echecs.length > 1 ? 's' : ''} laissé${echecs.length > 1 ? 's' : ''} intact${echecs.length > 1 ? 's' : ''} :</p>
      <ul class="sante-items">
        ${echecs.map(x => `<li class="sante-item"><span class="sante-item-nom">${esc(x.chemin.split(/[/\\]/).pop())}</span>
          <span class="sante-item-taille">${esc(x.message)}</span></li>`).join('')}
      </ul>` : ''}`;
  _actions(modal).innerHTML = '<button class="btn btn-ram" type="button" data-fermer>Fermer</button>';
  _actions(modal).querySelector('[data-fermer]').addEventListener('click', () => _fermer(modal));
  if (e.reussis) onRepare?.();
}
