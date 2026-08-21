const OPEN_KEY   = 'lib_open_animes';
const FAV_KEY    = 'lib_favoris_animes';
export const VIEWS_KEY  = 'lib_ep_views';
export const RESUME_KEY = 'lib_ep_resume';
export const NAMES_KEY  = 'lib_ep_names';

export function _getOpen()   { try { return new Set(JSON.parse(localStorage.getItem(OPEN_KEY) || '[]')); } catch { return new Set(); } }
export function _saveOpen(s) { try { localStorage.setItem(OPEN_KEY, JSON.stringify([...s])); } catch {} }
export function _getFavs()   { try { return new Set(JSON.parse(localStorage.getItem(FAV_KEY)  || '[]')); } catch { return new Set(); } }
export function _saveFavs(s) { try { localStorage.setItem(FAV_KEY,  JSON.stringify([...s])); } catch {} }
export function _getViews()  { try { return JSON.parse(localStorage.getItem(VIEWS_KEY) || '{}'); } catch { return {}; } }
export function _getResume() { try { return JSON.parse(localStorage.getItem(RESUME_KEY) || '{}'); } catch { return {}; } }
export function _getNames()  { try { return JSON.parse(localStorage.getItem(NAMES_KEY) || '{}'); } catch { return {}; } }
