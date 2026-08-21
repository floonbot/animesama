import { esc } from '../../utils/escape.js';
import { api } from '../../api.js';
import { toast } from '../../components/toast.js';
import { RESUME_KEY, VIEWS_KEY, _getResume, _getViews } from './storage.js';

let _playerKeyHandler = null;

function _detachPlayerKeyHandler() {
  if (_playerKeyHandler) {
    document.removeEventListener('keydown', _playerKeyHandler);
    _playerKeyHandler = null;
  }
}

window.lireEpisode = (fichier, playlist = [], idx = 0) => {

  _detachPlayerKeyHandler();
  document.getElementById('modal-player')?.remove();
  const resume  = _getResume();
  const startAt = resume[fichier] || 0;
  const modal   = document.createElement('div');
  modal.id      = 'modal-player';
  modal.className = 'modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Lecteur vidéo');
  const nom     = fichier.split(/[/\\]/).pop();
  const hasPrev = idx > 0;
  const hasNext = idx < playlist.length - 1;

  modal.innerHTML = `
    <div class="modal-backdrop" data-close></div>
    <div class="modal-box player-box">
      <div class="player-header">
        <div class="lib-ligne-8">
          <button class="player-nav-btn" id="player-prev" ${!hasPrev?'disabled':''} title="Épisode précédent">⏮</button>
          <span class="player-title">▶ ${esc(nom)}</span>
          <button class="player-nav-btn" id="player-next" ${!hasNext?'disabled':''} title="Épisode suivant">⏭</button>
        </div>
        <button class="modal-close lib-pos-static" data-close>✕</button>
      </div>
      <video class="lib-video" id="lib-video" controls autoplay
        src="/api/anime/stream?fichier=${encodeURIComponent(fichier)}">
      </video>
      <div class="player-progress-wrap">
        <span class="player-time" id="player-current">0:00</span>
        <input type="range" id="player-seek" class="player-seek" value="0" min="0" max="100" step="0.1">
        <span class="player-time" id="player-duration">0:00</span>
      </div>
      <div class="player-shortcuts">⌨️ Espace = Pause · ← → = ±5s · ↑ ↓ = Volume · F = Plein écran · M = Muet · N = Suivant</div>
    </div>`;
  document.body.appendChild(modal);
  modal.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', () => {
    modal.remove();
    _detachPlayerKeyHandler();
  }));

  const video   = document.getElementById('lib-video');
  const seek    = document.getElementById('player-seek');
  const curEl   = document.getElementById('player-current');
  const durEl   = document.getElementById('player-duration');
  const fmt     = s => `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;

  if (startAt > 30) video.addEventListener('loadedmetadata', () => { video.currentTime = startAt; }, { once: true });

  let _lastResumeSave = 0;
  video.addEventListener('timeupdate', () => {
    if (!video.duration) return;
    seek.value = (video.currentTime / video.duration * 100).toFixed(1);
    curEl.textContent = fmt(video.currentTime);
    const now = Date.now();
    if (now - _lastResumeSave >= 10_000) {
      _lastResumeSave = now;
      const r = _getResume();
      r[fichier] = Math.floor(video.currentTime);
      try { localStorage.setItem(RESUME_KEY, JSON.stringify(r)); } catch {}
    }
  });
  video.addEventListener('loadedmetadata', () => { durEl.textContent = fmt(video.duration); });
  video.addEventListener('ended', () => {
    const v = _getViews(); v[fichier] = (v[fichier] || 0) + 1;
    try { localStorage.setItem(VIEWS_KEY, JSON.stringify(v)); } catch {}
    const r = _getResume(); delete r[fichier];
    try { localStorage.setItem(RESUME_KEY, JSON.stringify(r)); } catch {}
  });
  seek.addEventListener('input', () => { video.currentTime = video.duration * seek.value / 100; });

  const goTo = (newIdx) => {
    if (newIdx < 0 || newIdx >= playlist.length) return;

    modal.remove();
    window.lireEpisode(playlist[newIdx], playlist, newIdx);
  };

  document.getElementById('player-prev')?.addEventListener('click', () => goTo(idx - 1));
  document.getElementById('player-next')?.addEventListener('click', () => goTo(idx + 1));

  _playerKeyHandler = (e) => {
    if (!document.getElementById('modal-player')) {
      _detachPlayerKeyHandler();
      return;
    }
    if (e.key === 'Escape')                   { modal.remove(); _detachPlayerKeyHandler(); }
    if (e.key === ' ')                         { e.preventDefault(); video.paused ? video.play() : video.pause(); }
    if (e.key === 'f' || e.key === 'F')        video.requestFullscreen?.();
    if (e.key === 'm' || e.key === 'M')        video.muted = !video.muted;
    if (e.key === 'n' || e.key === 'N')        goTo(idx + 1);
    if (e.key === 'ArrowRight' && !seek.matches(':focus')) { e.preventDefault(); video.currentTime += 5; }
    if (e.key === 'ArrowLeft'  && !seek.matches(':focus')) { e.preventDefault(); video.currentTime -= 5; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); video.volume = Math.min(1, video.volume + .1); }
    if (e.key === 'ArrowDown') { e.preventDefault(); video.volume = Math.max(0, video.volume - .1); }
  };
  document.addEventListener('keydown', _playerKeyHandler);
};

window.ouvrirDossier = async (fichier) => {
  try {
    const r = await api.post('/api/anime/ouvrir-dossier', { fichier });
    if (!r.ok) toast('❌ ' + (r.message || "Impossible d'ouvrir le dossier"), 'error');
  } catch { toast("Impossible d'ouvrir le dossier", 'error'); }
};
