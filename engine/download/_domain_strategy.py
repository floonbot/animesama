
import logging
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

from engine.config.settings import HOST_DOMAIN_REWRITES, HOSTS_MORTS, YTDLP_FIRST_DOMAINS
from engine.download.extractor.registry import (
    is_progressive_mp4 as _is_progressive_mp4,
)
from engine.download.extractor.registry import (
    prefer_ytdlp as _prefer_ytdlp,
)

log = logging.getLogger("engine.download.domain_strategy")

def hote_mort(domain: str) -> bool:
    if not domain:
        return False
    for d in HOSTS_MORTS:
        if domain == d or domain.endswith("." + d):
            return True
    return False

def reecrire_domaine(url: str) -> str:
    if not url or not HOST_DOMAIN_REWRITES:
        return url
    try:
        parts = urlsplit(url)
        cible = HOST_DOMAIN_REWRITES.get((parts.hostname or "").lower())
        if not cible:
            return url
        netloc = cible if parts.port is None else f"{cible}:{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except ValueError:
        return url

def get_domain(url: str) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def lecteur_url_valide(lecteur: dict[str, Any]) -> bool:
    src = lecteur.get("src", "")
    if not src or not isinstance(src, str):
        return False
    try:
        parsed = urlparse(src)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False

def strategie_lecteur(lecteur: dict[str, Any]) -> str:
    src    = lecteur.get("src", "")
    domain = get_domain(src)

    if domain in YTDLP_FIRST_DOMAINS:
        return "ytdlp_first"

    for d in YTDLP_FIRST_DOMAINS:
        if domain.endswith("." + d) or domain == d:
            return "ytdlp_first"

    if _prefer_ytdlp(src):
        return "ytdlp_first"

    return "playwright_first"

def partition_lecteurs(
    lecteurs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valides   = [l for l in lecteurs if isinstance(l, dict) and lecteur_url_valide(l)]
    invalides = len(lecteurs) - len(valides)
    if invalides:
        log.debug(
            f"partition_lecteurs : {invalides} lecteur(s) "
            f"avec URL invalide ignoré(s)"
        )

    vivants = [l for l in valides if not hote_mort(get_domain(l.get("src", "")))]
    morts = len(valides) - len(vivants)
    if morts:
        log.info(f"partition_lecteurs : {morts} lecteur(s) d'hôte(s) hors service ignoré(s)")

    ytdlp:  list[dict[str, Any]] = []
    autres: list[dict[str, Any]] = []
    for l in vivants:
        (ytdlp if strategie_lecteur(l) == "ytdlp_first" else autres).append(l)
    # Un hote qui a bride l'episode precedent passe en fin de liste plutot que
    # d'etre exclu : on le declasse, on ne le condamne pas.
    ytdlp.sort(key=lambda l: (_lecteur_lent(l), _is_progressive_mp4(l.get("src", ""))))
    autres.sort(key=_lecteur_lent)
    return ytdlp, autres

def _lecteur_lent(lecteur: dict[str, Any]) -> bool:
    from engine.download._debit import hote_lent

    return hote_lent(get_domain(reecrire_domaine(lecteur.get("src", ""))))
