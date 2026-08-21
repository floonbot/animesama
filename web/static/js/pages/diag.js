import { api } from '../api.js';
import { exportListe, showStatsModal } from './library/stats.js';

// Le rafraichissement periodique ne sert a rien quand la vue n'est pas devant
// l'utilisateur : le polling ne tourne que si la page diag est active *et* le
// document visible. Le SSE de l'app (events.js) fournit le reveil immediat,
// l'intervalle n'est que le filet quand le flux est coupe.
const FALLBACK_MS = 15000;

const $ = (id) => document.getElementById(id);

let live = false;
let logLevel = '';
let logTid = '';
let timer = null;
let debounce = null;
let visible = false;

function setLogTid(t) {
  logTid = t || '';
  tick();
}

function el(tag, props, children) {
  const node = document.createElement(tag);
  if (props) {
    for (const [k, val] of Object.entries(props)) {
      if (k === 'class') node.className = val;
      else if (k === 'style') node.style.cssText = val;
      else node.setAttribute(k, val);
    }
  }
  for (const c of children || []) {
    node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return node;
}

function row(k, v, cls) {
  return el('div', { class: 'row' }, [
    el('span', { class: 'k' }, [k]),
    el('span', { class: 'v' + (cls ? ' ' + cls : '') }, [String(v)]),
  ]);
}

function boolRow(k, v) {
  return row(k, v ? 'oui' : 'non', v ? 'ok' : 'ko');
}

function card(title, body, full) {
  return el('div', { class: 'card' + (full ? ' full' : '') }, [
    el('h2', null, [title]),
    ...body,
  ]);
}

function fmtDuree(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

function diskCard(label, d) {
  if (!d) return null;
  const bar = el('div', { class: 'bar' }, [
    el('i', { style: `width:${Math.min(100, d.used_pct || 0)}%` }, []),
  ]);
  return [
    row(`${label} — libre`, `${d.free_gb} Go`),
    row('total', `${d.total_gb} Go`),
    row('utilisé', `${d.used_pct} %`, d.used_pct >= 90 ? 'ko' : d.used_pct >= 75 ? 'warn' : 'ok'),
    bar,
  ];
}

function moteurTable(par) {
  const head = el('tr', null, [
    el('th', null, ['Moteur']),
    el('th', null, ['Tent.']),
    el('th', null, ['OK']),
    el('th', null, ['KO']),
    el('th', null, ['Succès']),
    el('th', null, ['Moy']),
    el('th', null, ['Débit']),
    el('th', null, ['Octets']),
  ]);
  const rows = [head];
  const names = Object.keys(par || {});
  if (!names.length) {
    return [el('div', { class: 'k' }, ['Aucun téléchargement moteur enregistré.'])];
  }
  for (const name of names) {
    const e = par[name];
    rows.push(el('tr', null, [
      el('td', null, [name]),
      el('td', null, [String(e.tentatives)]),
      el('td', null, [String(e.succes)]),
      el('td', null, [String(e.echecs)]),
      el('td', null, [`${e.taux_succes_pct} %`]),
      el('td', null, [`${e.temps_moyen_s}s`]),
      el('td', null, [`${e.debit_mo_s} Mo/s`]),
      el('td', null, [`${(e.octets / 1048576).toFixed(1)} Mo`]),
    ]));
  }
  return [el('table', null, rows)];
}

function latenceTable(lat) {
  const names = Object.keys(lat || {});
  if (!names.length) {
    return [el('div', { class: 'k' }, ['Aucune latence échantillonnée.'])];
  }
  const rows = [el('tr', null, [
    el('th', null, ['Phase']),
    el('th', null, ['p50']),
    el('th', null, ['p95']),
    el('th', null, ['max']),
  ])];
  for (const name of names) {
    const p = lat[name];
    rows.push(el('tr', null, [
      el('td', null, [name.replace(/_s$/, '')]),
      el('td', null, [`${p.p50}s`]),
      el('td', null, [`${p.p95}s`]),
      el('td', null, [`${p.max}s`]),
    ]));
  }
  return [el('table', null, rows)];
}

function hoteTable(par) {
  const names = Object.keys(par || {}).sort(
    (a, b) => (par[b].tentatives || 0) - (par[a].tentatives || 0),
  );
  if (!names.length) {
    return [el('div', { class: 'k' }, ['Aucune extraction par hôte enregistrée.'])];
  }
  const rows = [el('tr', null, [
    el('th', null, ['Hôte']),
    el('th', null, ['Tent.']),
    el('th', null, ['OK']),
    el('th', null, ['Succès']),
    el('th', null, ['']),
  ])];
  for (const name of names) {
    const e = par[name];
    const pct = e.taux_succes_pct || 0;
    const cls = pct >= 80 ? 'ok' : pct >= 50 ? 'warn' : 'ko';
    const bar = el('div', { class: 'bar' }, [
      el('i', { style: `width:${Math.min(100, pct)}%` }, []),
    ]);
    rows.push(el('tr', null, [
      el('td', null, [name]),
      el('td', null, [String(e.tentatives)]),
      el('td', null, [String(e.succes)]),
      el('td', { class: cls }, [`${pct} %`]),
      el('td', null, [bar]),
    ]));
  }
  return [el('table', null, rows)];
}

const LIEN_LABELS = {
  ytdlp_direct: 'yt-dlp direct',
  network_parallel: 'Interception parallèle',
  network_seq: 'Interception séquentielle',
  browser_forensic: 'Extraction forensic',
};

function liensBody(liens, hotes) {
  const body = [];
  const keys = Object.keys(liens || {});
  if (!keys.length) {
    body.push(el('div', { class: 'k' }, ['Aucune extraction réussie enregistrée.']));
  } else {
    const total = keys.reduce((s, k) => s + (liens[k] || 0), 0) || 1;
    keys.sort((a, b) => (liens[b] || 0) - (liens[a] || 0));
    for (const k of keys) {
      const n = liens[k] || 0;
      body.push(row(LIEN_LABELS[k] || k, `${n} · ${Math.round((100 * n) / total)} %`));
    }
  }
  const names = (hotes || []).map((h) => h.name);
  body.push(row('Hôtes supportés', names.length ? String(names.length) : '0'));
  if (names.length) body.push(el('div', { class: 'k' }, [names.join(' · ')]));
  return body;
}

const LEVEL_CLASS = { ERROR: 'ko', CRITICAL: 'ko', WARNING: 'warn', OK: 'ok' };

function logsBody(logs) {
  const out = [];
  if (logTid) {
    const clear = el('button', { class: 'log-clear', type: 'button' }, ['✕ tout']);
    clear.addEventListener('click', () => setLogTid(''));
    out.push(el('div', { class: 'log-filter' }, [
      el('span', { class: 'k' }, ['filtre tâche']),
      el('span', { class: 'lid' }, ['[' + logTid + ']']),
      clear,
    ]));
  }
  const entries = (logs && logs.logs) || [];
  if (!entries.length) {
    out.push(el('div', { class: 'k' }, ['Aucune ligne récente.']));
    return out;
  }
  const lines = [];
  for (const e of entries) {
    const d = new Date((e.ts || 0) * 1000);
    const t =
      String(d.getHours()).padStart(2, '0') + ':' +
      String(d.getMinutes()).padStart(2, '0') + ':' +
      String(d.getSeconds()).padStart(2, '0');
    const kids = [
      el('span', { class: 'lt' }, [t]),
      el('span', { class: 'lv ' + (LEVEL_CLASS[e.level] || 'dim') }, [e.level || '']),
      el('span', { class: 'll' }, [(e.logger || '').split('.').pop()]),
    ];
    if (e.tid) kids.push(el('span', { class: 'lid' }, ['[' + e.tid + ']']));
    kids.push(el('span', { class: 'lm' }, [e.msg || '']));
    const line = el('div', { class: 'logline' + (e.tid ? ' clickable' : '') }, kids);
    if (e.tid) {
      line.setAttribute('title', 'Filtrer sur la tâche ' + e.tid);
      line.addEventListener('click', () => setLogTid(e.tid));
    }
    lines.push(line);
  }
  out.push(el('div', { class: 'logbox' }, lines));
  return out;
}

const SOURCE_BUILD = {
  sources: 'sources de développement',
  paquet_sans_tampon: 'paquet sans horodatage',
  inconnu: 'indéterminé',
};

// Le raccourci lance l'application installee, pas le depot : sans cette ligne
// rien ne distingue a l'ecran un paquet d'avant-hier d'un paquet du jour.
function libelleBuild(b) {
  if (!b) return '?';
  if (SOURCE_BUILD[b.source]) return SOURCE_BUILD[b.source];
  if (!b.built_at) return b.built_at_iso || '?';
  const d = new Date(b.built_at * 1000);
  const p = (n) => String(n).padStart(2, '0');
  const date = `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  // « Python » du build, pas celui qui tourne : sur un paquet ils coïncident,
  // mais c'est l'interpréteur choisi par `py -3` au build — pas forcément celui
  // sous lequel la suite de tests passe.
  const bouts = [`paquet du ${date}`];
  if (b.git) bouts.push(b.git);
  if (b.python) bouts.push(`Python ${b.python}`);
  return bouts.join(' · ');
}

// Stats et Export viennent de la barre d'outils de la librairie. Les y laisser
// obligeait a ouvrir cette page pour que les donnees se chargent ; ici la carte
// va les chercher elle-meme, au meme rythme que le reste du diagnostic.
function librairieBody(lib) {
  const animes = (lib && lib.animes) || [];
  if (!animes.length) {
    return [el('div', { class: 'k' }, [
      lib ? 'Aucun anime téléchargé.' : 'Librairie indisponible.',
    ])];
  }

  const totalEps = animes.reduce((s, a) => s + (a.total_eps || 0), 0);
  const totalGo = animes.reduce((s, a) => s + (a.total_size || 0), 0);

  const bouton = (texte, onClick) => {
    const b = el('button', { class: 'btn btn-sm btn-ghost', type: 'button' }, [texte]);
    b.addEventListener('click', () => onClick(animes));
    return b;
  };

  return [
    row('Animes', animes.length),
    row('Épisodes', totalEps),
    row('Stockage', `${totalGo.toFixed(2)} Go`),
    el('div', { class: 'diag-lib-actions' }, [
      bouton('📊 Statistiques', showStatsModal),
      bouton('📥 Exporter en CSV', exportListe),
    ]),
  ];
}

function render(health, metr, logs, lib) {
  const cards = $('diag-cards');
  if (!cards) return;
  cards.replaceChildren();
  const r = (metr && metr.resume) || {};
  const g = (metr && metr.gauges) || {};
  const c = (metr && metr.metrics) || {};

  const proc = (health && health.process) || {};
  const etatRows = [
    boolRow('Service', !!(health && health.ok)),
    row('Version', (health && health.version) || '?'),
    row('Build', libelleBuild(health && health.build)),
    row('Uptime', fmtDuree(proc.uptime_s != null ? proc.uptime_s : r.uptime_s)),
    row('Plateforme', proc.platform || '?'),
    row('Python', proc.python || '?'),
    row('PID', proc.pid != null ? proc.pid : '?'),
  ];
  if (proc.memory_mb != null) etatRows.push(row('Mémoire', `${proc.memory_mb} Mo`));
  if (proc.cpu_pct != null) {
    etatRows.push(row('CPU', `${proc.cpu_pct} %`, proc.cpu_pct >= 80 ? 'warn' : ''));
  }
  if (proc.threads != null) etatRows.push(row('Threads', proc.threads));
  cards.appendChild(card('État', etatRows));

  const q = (health && health.queue) || {};
  cards.appendChild(card("File d'attente", [
    boolRow('En cours', !!q.en_cours),
    row('En attente', q.pending != null ? q.pending : '?'),
    row('Profondeur max', g.queue_depth_max != null ? g.queue_depth_max : (r.queue_depth_max || 0)),
    boolRow('En pause', !!q.en_pause),
  ]));

  const a = (health && health.auth) || {};
  cards.appendChild(card('Authentification', [
    boolRow('Connecté', !!a.connected),
    row('Cookies', a.cookies != null ? a.cookies : '?'),
    boolRow('Keepalive actif', !!a.keepalive),
  ]));

  const eng = (health && health.engines) || {};
  cards.appendChild(card('Moteurs & navigateur', [
    boolRow('N_m3u8DL-RE', !!eng.nm3u8dl),
    boolRow('yt-dlp', !!eng.ytdlp),
    boolRow('ffmpeg', !!eng.ffmpeg),
    boolRow('Navigateur', !!(health && health.browser)),
  ]));

  const br = (health && health.breakers) || {};
  const brOpen = br.open || [];
  const brHalf = br.half_open || [];
  const brBody = [];
  if (!brOpen.length && !brHalf.length) {
    brBody.push(el('div', { class: 'k' }, ['Tous fermés — aucun hôte coupé.']));
  } else {
    if (brOpen.length) brBody.push(row('Ouverts (coupés)', brOpen.join(', '), 'ko'));
    if (brHalf.length) brBody.push(row('Semi-ouverts (test)', brHalf.join(', '), 'warn'));
  }
  cards.appendChild(card('Disjoncteurs hôtes', brBody));

  cards.appendChild(card('Librairie', librairieBody(lib)));

  const disk = (health && health.disk) || {};
  const diskBody = [];
  for (const [lbl, key] of [['Animes', 'downloads'], ['Scans', 'scans'], ['Temp', 'temp']]) {
    const part = diskCard(lbl, disk[key]);
    if (part) diskBody.push(...part);
  }
  if (!diskBody.length) diskBody.push(el('div', { class: 'k' }, ['Indisponible.']));
  cards.appendChild(card('Disque', diskBody));

  const sse = (health && health.sse) || {};
  cards.appendChild(card('Flux SSE', [
    row('Clients connectés', sse.clients != null ? sse.clients : (g.sse_clients || 0)),
    row('Events envoyés', c.sse_events_sent || 0),
    row('Events droppés', c.sse_events_dropped || 0, (c.sse_events_dropped || 0) > 0 ? 'warn' : ''),
  ]));

  const httpm = r.http || {};
  const tauxErr = httpm.taux_erreur_pct || 0;
  cards.appendChild(card('API (requêtes)', [
    row('Total (hors diag)', httpm.total != null ? httpm.total : 0),
    row('2xx / 3xx', `${httpm.reponses_2xx || 0} / ${httpm.reponses_3xx || 0}`),
    row('Erreurs 4xx', httpm.erreurs_4xx || 0, (httpm.erreurs_4xx || 0) > 0 ? 'warn' : ''),
    row('Erreurs 5xx', httpm.erreurs_5xx || 0, (httpm.erreurs_5xx || 0) > 0 ? 'ko' : ''),
    row("Taux d'erreur", tauxErr + ' %', tauxErr >= 10 ? 'ko' : tauxErr > 0 ? 'warn' : 'ok'),
    row('Polling diag / media', `${httpm.diag || 0} / ${httpm.media || 0}`),
  ]));

  cards.appendChild(card('Débit & succès', [
    row('Débit global', `${r.debit_global_mo_s || 0} Mo/s`),
    row('Taux succès épisodes', `${r.taux_succes_pct || 0} %`,
      (r.taux_succes_pct || 0) >= 80 ? 'ok' : (r.taux_succes_pct || 0) >= 50 ? 'warn' : 'ko'),
    row('Volume total', `${r.go_total || 0} Go`),
    row('Épisodes ok / ko / skip',
      `${r.episodes_ok || 0} / ${r.episodes_ko || 0} / ${r.episodes_skip || 0}`),
    row('Items annulés / erreur', `${r.items_annules || 0} / ${r.items_erreur || 0}`),
    row('Durée moyenne / item', `${r.duree_moyenne_s || 0}s`),
    row('Interception moyenne', `${r.interception_moyenne_s || 0}s`),
    row('Cache (hit)', `${r.cache_hit_pct || 0} %`),
  ]));

  cards.appendChild(card('Par moteur', moteurTable(r.par_moteur), true));

  const hoteBody = hoteTable(r.par_hote);
  const degrades = r.hotes_degrades || [];
  if (degrades.length) {
    hoteBody.unshift(el('div', { class: 'row' }, [
      el('span', { class: 'k' }, ['⚠ Hôtes dégradés']),
      el('span', { class: 'v ko' }, [degrades.join(', ')]),
    ]));
  }
  cards.appendChild(card('Succès par hôte', hoteBody, true));

  const canon = r.par_hote_canonique || {};
  if (Object.keys(canon).length) {
    const canonBody = hoteTable(canon);
    const degCanon = r.hotes_degrades_canonique || [];
    if (degCanon.length) {
      canonBody.unshift(el('div', { class: 'row' }, [
        el('span', { class: 'k' }, ['⚠ Hôtes dégradés']),
        el('span', { class: 'v ko' }, [degCanon.join(', ')]),
      ]));
    }
    cards.appendChild(card('Succès par hôte (consolidé)', canonBody, true));
  }

  cards.appendChild(card("Maillon d'extraction gagnant", liensBody(r.extraction_par_lien, r.hotes_supportes)));
  cards.appendChild(card('Latences (s)', latenceTable(r.latences), true));
  cards.appendChild(card('Journal récent', logsBody(logs), true));
}

function setStatus(ok, text) {
  const dot = $('diag-status-dot');
  if (dot) dot.className = 'diag-dot ' + (ok ? 'ok' : 'ko');
  const txt = $('diag-status-text');
  if (txt) txt.textContent = text;
}

async function tick() {
  try {
    let logsUrl = '/api/logs?limit=60';
    if (logLevel) logsUrl += '&level=' + encodeURIComponent(logLevel);
    if (logTid) logsUrl += '&tid=' + encodeURIComponent(logTid);
    const [health, metr, logs, lib] = await Promise.all([
      api.get('/api/health'),
      api.get('/api/metrics'),
      api.get(logsUrl).catch(() => null),
      // Le meme cache que la page Librairie : revenir ici toutes les 15 s ne
      // relance pas un scan du disque.
      api.getCached('/api/anime/librairie', 30000).catch(() => null),
    ]);
    render(health, metr, logs, lib);
    const base = health.ok ? 'Instance en ligne' : 'Anomalie détectée';
    setStatus(!!health.ok, base + (live ? ' · live' : ''));
    const d = new Date();
    const maj = $('diag-last-update');
    if (maj) {
      maj.textContent =
        'maj ' + String(d.getHours()).padStart(2, '0') + ':' +
        String(d.getMinutes()).padStart(2, '0') + ':' +
        String(d.getSeconds()).padStart(2, '0');
    }
  } catch (e) {
    setStatus(false, 'Hors ligne — ' + (e && e.message ? e.message : 'erreur'));
  }
}

function scheduleTick() {
  if (!visible || debounce) return;
  debounce = setTimeout(() => { debounce = null; tick(); }, 800);
}

function applyAuto() {
  if (timer) { clearInterval(timer); timer = null; }
  if (visible && $('diag-auto')?.checked) timer = setInterval(tick, FALLBACK_MS);
}

function setVisible(on) {
  if (on === visible) return;
  visible = on;
  applyAuto();
  if (visible) tick();
}

function pageActive() {
  return !!document.getElementById('page-diag')?.classList.contains('active');
}

export function initDiag() {
  $('diag-refresh')?.addEventListener('click', tick);
  $('diag-auto')?.addEventListener('change', applyAuto);
  $('diag-log-level')?.addEventListener('change', () => {
    logLevel = $('diag-log-level').value;
    tick();
  });

  window.addEventListener('page-changed', () => {
    setVisible(pageActive() && !document.hidden);
  });
  document.addEventListener('visibilitychange', () => {
    setVisible(pageActive() && !document.hidden);
  });

  window.addEventListener('sse-activity', scheduleTick);
  window.addEventListener('sse-state', (e) => {
    live = !!e.detail?.live;
    if (live) scheduleTick();
  });
}
