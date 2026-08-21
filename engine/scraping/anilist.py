import logging
import os
import re

import requests

from engine.cache.disk_cache import DiskCache

log = logging.getLogger("engine.scraping.anilist")

ANILIST_URL = "https://graphql.anilist.co"
ANILIST_TIMEOUT = 8

_ENABLED = os.getenv("ANILIST_COHERENCE", "1").strip().lower() not in ("0", "false", "no")
_disk = DiskCache("anilist", 7 * 86400, cap=1000)

_QUERY = (
    "query ($s: String) {"
    "  Media(search: $s, type: ANIME, format_in: [TV, TV_SHORT, ONA]) {"
    "    id title { romaji english } episodes format status"
    "  }"
    "}"
)

def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

def _fetch_sync(titre: str):
    try:
        r = requests.post(
            ANILIST_URL,
            json={"query": _QUERY, "variables": {"s": titre}},
            timeout=ANILIST_TIMEOUT,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if r.status_code != 200:
            return None
        return (r.json().get("data") or {}).get("Media")
    except Exception:
        log.debug("AniList fetch échoué (%s)", titre[:60], exc_info=True)
        return None

def _match_exact(titre_as: str, media: dict) -> bool:
    cible = _norm(titre_as)
    if len(cible) < 4:
        return False
    t = media.get("title") or {}
    return any(_norm(t.get(k)) == cible for k in ("romaji", "english"))

def canon_saison1(titre: str):
    if not _ENABLED:
        return None
    cle = _norm(titre)
    if not cle:
        return None
    cached = _disk.get(cle)
    if cached is not None:
        return cached
    media = _fetch_sync(titre)
    if not media:
        return None
    if _match_exact(titre, media):
        result = {
            "matched": True,
            "episodes": media.get("episodes"),
            "finished": media.get("status") == "FINISHED",
        }
    else:
        result = {"matched": False, "episodes": None, "finished": False}
    _disk.set(cle, result)
    return result
