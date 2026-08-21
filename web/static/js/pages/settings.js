import { api } from '../api.js';
import { toast } from '../components/toast.js';
import { navigateTo } from '../router.js';
import { SUJET_REGLAGES, signalerChangement } from '../utils/vue-live.js';

const $ = (id) => document.getElementById(id);

// Les champs de dossier acceptent le vide (« = dossier par defaut »), et le
// dossier configure peut etre injoignable, auquel cas la resolution retombe sur
// le defaut. /api/health porte le chemin resolu — mais l'afficher a cote du
// verdict repetait deux fois la meme phrase quand les deux coincidaient. Il ne
// vaut donc qu'en complement, et seulement quand il DIFFERE de la saisie.
const CHAMPS_DOSSIER = [
  ['set-dldir', 'downloads'],
  ['set-scandir', 'scans'],
];

const IDS_DOSSIER = CHAMPS_DOSSIER.map(([id]) => id);
const CLE_DISQUE = Object.fromEntries(CHAMPS_DOSSIER);

let _chargement = null;
let _cheminsReels = {};
let _valeursEnregistrees = {};
const _seqVerif = {};

function _pontNatif() {
  const api_ = window.pywebview && window.pywebview.api;
  return api_ && typeof api_.choisir_dossier === 'function' ? api_ : null;
}

// Windows ignore la casse et tolere les deux separateurs : comparer les chaines
// brutes annoncait un repli la ou il n'y en avait pas.
function _memeChemin(a, b) {
  const norme = (s) => String(s || '').replace(/[\\/]+/g, '\\').replace(/\\+$/, '').toLowerCase();
  return norme(a) === norme(b);
}

async function _chargerCheminsReels() {
  try {
    const sante = await api.get('/api/health');
    const disk = sante?.disk || {};
    _cheminsReels = Object.fromEntries(
      CHAMPS_DOSSIER.map(([id, cle]) => [id, disk[cle]?.path || '']),
    );
  } catch {
    _cheminsReels = {};
  }
}

// Le chemin resolu ne vaut que si le champ montre encore la valeur enregistree :
// sur une saisie non sauvegardee, /api/health decrit l'ancien reglage et
// signalerait un repli imaginaire.
function _complementRepli(champId, saisi) {
  const reel = _cheminsReels[champId];
  if (!reel) return '';
  if (saisi !== (_valeursEnregistrees[champId] ?? '')) return '';
  if (!saisi) return reel;
  return _memeChemin(saisi, reel) ? '' : reel;
}

function _afficherVerdict(champId, d) {
  const el = $(`${champId}-verdict`);
  if (!el) return;
  if (!d) {
    el.textContent = '';
    el.className = 'set-help set-verdict';
    return;
  }
  const saisi = ($(champId)?.value || '').trim();
  const repli = _complementRepli(champId, saisi);

  if (d.defaut) {
    el.textContent = repli
      ? `Dossier par défaut : ${repli}`
      : 'Dossier par défaut de l\'application';
    el.className = 'set-help set-verdict';
    return;
  }
  el.textContent = repli && !d.ok
    ? `${d.message} — les fichiers vont dans ${repli} à la place`
    : (d.message || '');
  el.className = 'set-help set-verdict ' +
    (d.ok ? (d.creable ? 'set-verdict-avertit' : 'set-verdict-ok') : 'set-verdict-ko');
}

// Jeton de sequence : un chemin UNC injoignable bloque une vingtaine de
// secondes cote serveur. Sans ce garde, corriger entre-temps par un chemin
// local qui repond en 5 ms laissait la reponse tardive ecraser l'affichage par
// le verdict d'un chemin que le champ ne contient plus. Seul l'affichage est
// concerne : l'appelant recoit toujours le verdict qu'il a demande.
async function _verifier(champId) {
  const champ = $(champId);
  if (!champ) return null;
  const chemin = champ.value.trim();
  const seq = (_seqVerif[champId] = (_seqVerif[champId] || 0) + 1);
  const frais = () => _seqVerif[champId] === seq;

  if (!chemin) {
    const d = { defaut: true, ok: true };
    if (frais()) _afficherVerdict(champId, d);
    return d;
  }
  try {
    const d = await api.get(
      `/api/settings/verifier-dossier?chemin=${encodeURIComponent(chemin)}`,
    );
    if (frais()) _afficherVerdict(champId, d);
    return d;
  } catch {
    if (frais()) _afficherVerdict(champId, null);
    return null;
  }
}

function _debounce(fn, ms) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export async function chargerReglages() {
  if (_chargement) return _chargement;
  _chargement = (async () => {
    try {
      const s = await api.getCached('/api/settings', 30000);
      $('set-qualite').value = s.qualite || 'auto';
      $('set-threads').value = s.thread_count || 16;
      $('thread-val').textContent = s.thread_count || 16;
      $('set-dldir').value = s.downloads_dir || '';
      const scd = $('set-scandir');
      if (scd) scd.value = s.scans_dir || '';
      $('set-notifs').checked = s.notifications !== false;
      const son = $('set-son');
      if (son) son.checked = s.son_notif !== false;
      const skip = $('set-skip');
      if (skip) skip.checked = s.skip_existants !== false;
      const conf = $('set-confirm');
      if (conf) conf.checked = s.confirm_suppr !== false;
      const lang = $('set-langue');
      if (lang) lang.value = s.langue_defaut || 'VOSTFR';
      _valeursEnregistrees = {
        'set-dldir': (s.downloads_dir || '').trim(),
        'set-scandir': (s.scans_dir || '').trim(),
      };
    } catch { /* les valeurs du gabarit restent affichées */ }
    // Le chemin resolu doit etre connu avant le premier verdict : il en est un
    // morceau, et l'afficher apres coup faisait clignoter la ligne.
    await _chargerCheminsReels();
    await Promise.all(IDS_DOSSIER.map(_verifier));
  })().finally(() => { _chargement = null; });
  return _chargement;
}

// Le serveur cree le dossier absent au moment de la sauvegarde : la sonde ne
// cree rien, ce qui laisse la place a une confirmation avant que la faute de
// frappe ne fabrique un dossier fantome.
function _confirmerCreations(verdicts) {
  const aCreer = verdicts.filter((d) => d && d.ok && d.creable);
  if (!aCreer.length) return true;
  const liste = aCreer.map((d) => d.chemin).join('\n');
  return window.confirm(
    `Ce dossier n'existe pas encore et va être créé :\n\n${liste}\n\nContinuer ?`,
  );
}

async function _sauvegarder() {
  const errEl = $('settings-error');
  errEl.classList.add('hidden');

  // Les verdicts sont lus dans le tableau rendu, pas dans un etat partage : une
  // sonde de frappe qui atterrit entre-temps ne peut pas changer la decision.
  const verdicts = await Promise.all(IDS_DOSSIER.map(_verifier));
  const refus = verdicts.find((d) => d && !d.ok);
  if (refus) {
    errEl.textContent = refus.message || 'Dossier invalide';
    errEl.classList.remove('hidden');
    return;
  }
  if (!_confirmerCreations(verdicts)) return;

  const body = {
    qualite:        $('set-qualite').value,
    thread_count:   parseInt($('set-threads').value, 10),
    downloads_dir:  $('set-dldir').value.trim(),
    scans_dir:      $('set-scandir')?.value.trim(),
    notifications:  $('set-notifs').checked,
    son_notif:      $('set-son')?.checked,
    skip_existants: $('set-skip')?.checked,
    confirm_suppr:  $('set-confirm')?.checked,
    langue_defaut:  $('set-langue')?.value,
  };

  const btn = $('settings-save');
  if (btn) btn.disabled = true;
  try {
    const r = await api.post('/api/settings', body);
    api.invalidateCache('/api/settings');
    if (r.ok) {
      // Changer de dossier de telechargement change ce que la librairie montre,
      // et le son de notification est lu par la page des telechargements : les
      // vues deja rendues doivent l'apprendre.
      api.invalidateCache('/api/anime/librairie');
      signalerChangement(SUJET_REGLAGES);
      toast('✅ Paramètres sauvegardés', 'success');
      _marquerEtat('Enregistré');
      // Le serveur a pu creer le dossier ou retomber sur le defaut : le verdict
      // affiche doit repartir de ce qui est desormais enregistre.
      _valeursEnregistrees = {
        'set-dldir': body.downloads_dir || '',
        'set-scandir': body.scans_dir || '',
      };
      await _chargerCheminsReels();
      await Promise.all(IDS_DOSSIER.map(_verifier));
    } else {
      errEl.textContent = r.message || 'Erreur';
      errEl.classList.remove('hidden');
    }
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove('hidden');
  } finally {
    if (btn) btn.disabled = false;
  }
}

let _etatTimer = null;
function _marquerEtat(txt) {
  const el = $('settings-etat');
  if (!el) return;
  el.textContent = txt;
  clearTimeout(_etatTimer);
  _etatTimer = setTimeout(() => { el.textContent = ''; }, 4000);
}

async function _parcourir(btn) {
  const pont = _pontNatif();
  const champ = $(btn.dataset.cible);
  if (!pont || !champ) return;
  try {
    const choix = await pont.choisir_dossier(champ.value.trim());
    if (choix) {
      champ.value = choix;
      await _verifier(btn.dataset.cible);
    }
  } catch {
    toast("Le sélecteur de dossier n'a pas pu s'ouvrir", 'error');
  }
}

// Le pont n'existe que dans la fenetre de bureau, et pywebview l'injecte apres
// le chargement du document : on l'attend au lieu de conclure trop tot que
// l'interface tourne dans un navigateur.
function _revelerParcourir() {
  if (!_pontNatif()) return false;
  document.querySelectorAll('.set-parcourir').forEach((b) => b.classList.remove('hidden'));
  return true;
}

export function initSettings() {
  if (!$('page-parametres')) return;

  $('set-threads')?.addEventListener('input', (e) => {
    const v = $('thread-val');
    if (v) v.textContent = e.target.value;
  });

  const revalider = _debounce((id) => _verifier(id), 400);
  for (const id of IDS_DOSSIER) {
    $(id)?.addEventListener('input', () => revalider(id));
    $(id)?.addEventListener('blur', () => _verifier(id));
  }

  $('settings-save')?.addEventListener('click', _sauvegarder);
  $('settings-cancel')?.addEventListener('click', () => {
    api.invalidateCache('/api/settings');
    chargerReglages();
    _marquerEtat('Modifications annulées');
  });
  $('settings-form')?.addEventListener('submit', (e) => {
    e.preventDefault();
    _sauvegarder();
  });
  $('settings-diag')?.addEventListener('click', () => navigateTo('diag'));

  document.querySelectorAll('.set-parcourir').forEach((b) => {
    b.addEventListener('click', () => _parcourir(b));
  });

  if (!_revelerParcourir()) {
    window.addEventListener('pywebviewready', _revelerParcourir, { once: true });
  }

  // Les reglages viennent du serveur et peuvent avoir change dans un autre
  // onglet ou un autre profil : on relit a chaque arrivee sur la page.
  window.addEventListener('page-changed', (e) => {
    if (e.detail?.page === 'parametres') chargerReglages();
  });
}
