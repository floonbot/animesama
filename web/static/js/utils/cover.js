export function coverSrc(url) {
  if (!url) return '';
  if (url.startsWith('data:') || url.startsWith('/')) return url;
  return '/api/anime/cover?u=' + encodeURIComponent(url);
}
