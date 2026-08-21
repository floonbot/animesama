import { api } from '../../api.js';

let _libSettings = null;
(async () => {
  try { _libSettings = await api.getCached('/api/settings', 30000); } catch {}
})();

export function confirmSuppression(btn) {
  if (_libSettings && _libSettings.confirm_suppr === false) return true;
  if (btn.dataset.confirm === '1') return true;
  btn.dataset.confirm = '1';
  const ancien = btn.textContent;
  btn.textContent = '⚠️';
  btn.style.background = 'rgba(255,100,0,.25)';
  setTimeout(() => {
    btn.dataset.confirm = '';
    btn.textContent = ancien;
    btn.style.background = '';
  }, 3000);
  return false;
}
