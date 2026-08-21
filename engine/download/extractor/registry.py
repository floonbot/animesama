
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from engine.download._patterns import media_kind as _media_kind

log = logging.getLogger("engine.download.extractor.registry")

__all__ = [
    "HostExtractor",
    "register",
    "get_extractor",
    "canonical_host",
    "prefer_ytdlp",
    "host_headers",
    "extractor_args",
    "media_kind",
    "supported_hosts",
]

@dataclass(frozen=True)
class HostExtractor:
    name: str
    domains: tuple[str, ...] = ()
    prefer_ytdlp: bool = False
    referer: str = ""
    origin: str = ""
    user_agent: str = ""
    extractor_args: str = ""
    no_aria2c: bool = False
    # Fait verifier le certificat par le magasin du systeme au lieu du certifi
    # embarque dans yt-dlp. La verification reste entiere — c'est le magasin,
    # pas la confiance, qui change. Par hote et jamais globalement : mesure sur
    # les 27 hotes connus, le magasin Windows repare myvi.tv mais ne connait pas
    # les racines de vk.com, vkvideo.ru et ok.ru, que certifi couvre.
    sans_certifi: bool = False
    progressive_mp4: bool = False
    note: str = ""

    def matches(self, host: str) -> bool:
        if not host:
            return False
        for d in self.domains:
            if host == d or host.endswith("." + d):
                return True
        return False

_GENERIC = HostExtractor(name="generic", note="Filet generique : sniff m3u8/mpd/mp4 capte au reseau")
_REGISTRY: list[HostExtractor] = []
_loaded = False

def register(extractor: HostExtractor) -> HostExtractor:
    for existing in _REGISTRY:
        if existing.name == extractor.name:
            return existing
    _REGISTRY.append(extractor)
    return extractor

def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        from engine.download.extractor import hosts as _hosts  # noqa: F401
    except Exception:
        log.debug("chargement des extracteurs par hote echoue", exc_info=True)

def _host_of(host_or_url: str) -> str:
    if not host_or_url:
        return ""
    s = host_or_url.strip()
    if "://" in s:
        try:
            return (urlparse(s).hostname or "").lower().rstrip(".")
        except Exception:
            return ""
    s = s.lower()
    if "/" in s:
        s = s.split("/", 1)[0]
    if "@" in s:
        s = s.split("@", 1)[1]
    if ":" in s:
        s = s.split(":", 1)[0]
    return s.rstrip(".")

def _labels_marque(ext: HostExtractor) -> set[str]:
    labels: set[str] = set()
    for d in ext.domains:
        parts = d.split(".")
        if len(parts) >= 2 and len(parts[-2]) >= 5:
            labels.add(parts[-2])
    return labels

def get_extractor(host_or_url: str) -> HostExtractor:
    _ensure_loaded()
    host = _host_of(host_or_url)
    for ext in _REGISTRY:
        if ext.matches(host):
            return ext
    parts = host.split(".")
    if len(parts) >= 2 and len(parts[-2]) >= 5:
        marque = parts[-2]
        for ext in _REGISTRY:
            if marque in _labels_marque(ext):
                return ext
    return _GENERIC

def canonical_host(host_or_url: str) -> str:
    _ensure_loaded()
    host = _host_of(host_or_url)
    for ext in _REGISTRY:
        if ext.matches(host):
            return ext.name
    return host

def prefer_ytdlp(host_or_url: str) -> bool:
    return get_extractor(host_or_url).prefer_ytdlp

def is_progressive_mp4(host_or_url: str) -> bool:
    return get_extractor(host_or_url).progressive_mp4

def host_headers(url: str, base: dict[str, str] | None = None) -> dict[str, str]:
    out: dict[str, str] = dict(base or {})
    ext = get_extractor(url)
    if ext.referer:
        out["referer"] = ext.referer
    if ext.origin:
        out["origin"] = ext.origin
    if ext.user_agent:
        out["user-agent"] = ext.user_agent
    return out

def extractor_args(url: str) -> str:
    return get_extractor(url).extractor_args

def media_kind(url: str) -> str | None:
    return _media_kind(url)

def supported_hosts() -> list[dict]:
    _ensure_loaded()
    out: list[dict] = []
    for ext in _REGISTRY:
        out.append({
            "name": ext.name,
            "domains": list(ext.domains),
            "strategy": "yt-dlp" if ext.prefer_ytdlp else "playwright",
            "note": ext.note,
        })
    return out
