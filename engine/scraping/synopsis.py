"""Synopsis d'une oeuvre, pour les fiches de la librairie et des favoris.

Un synopsis ne change quasiment jamais : cache disque d'une semaine, et une
fiche sans synopsis est retenue aussi (chaine vide) pour ne pas la redemander a
chaque ouverture. Un echec reseau, lui, n'est pas retenu.
"""

import asyncio
import logging
import re

from engine.cache.disk_cache import DiskCache
from engine.scraping.http_client import _is_safe_url, http_get
from engine.scraping.site.animessama import SITE_URL

log = logging.getLogger("engine.scraping.synopsis")

_TTL_S = 7 * 86400
# Changer la version quand parse_synopsis rend autre chose pour une meme page.
_disk = DiskCache("synopsis", _TTL_S, cap=1000, version="1")
_RE_SLUG = re.compile(r"/catalogue/([^/?#]+)")

# Nom de dossier de la librairie -> fiche, pour la session : la recherche sur le
# site est un POST qu'on ne refait pas a chaque ouverture.
_url_par_nom: dict[str, str] = {}


def fiche_de(url: str) -> str:
    m = _RE_SLUG.search(url or "")
    return f"{SITE_URL}/catalogue/{m.group(1)}" if m else ""


async def get_synopsis_async(url: str) -> str:
    from engine.auth.manager import auth_manager
    from engine.scraping.parser import parse_synopsis

    # fiche_de reconstruit l'adresse sur le site a partir du seul slug : sans ce
    # controle, l'URL d'un autre hote rendrait le synopsis d'une homonyme.
    fiche = fiche_de(url) if _is_safe_url(url) else ""
    if not fiche:
        return ""
    connu = await asyncio.to_thread(_disk.get, fiche)
    if connu is not None:
        return connu
    r = await http_get(fiche, auth_manager.cookies)
    if not r:
        return ""
    texte = await asyncio.to_thread(parse_synopsis, r.text)
    await asyncio.to_thread(_disk.set_many, {fiche: texte})
    return texte


async def url_pour_nom(nom: str) -> str:
    """Retrouve la fiche d'un anime de la librairie, comme le fait « Nouveautes ».

    D'abord les listes du compte, puis la recherche du site — sur un nom
    identique une fois normalise, jamais sur le premier resultat venu : un
    synopsis d'une autre oeuvre serait pire que pas de synopsis.
    """
    from engine.library.updates import normaliser_nom
    from engine.scraping.favorites import get_favorites_async
    from engine.scraping.search import search_async

    cle = normaliser_nom(nom)
    if not cle:
        return ""
    if cle in _url_par_nom:
        return _url_par_nom[cle]
    try:
        favoris = await get_favorites_async()
    except Exception:
        log.debug("synopsis : favoris indisponibles", exc_info=True)
        favoris = []
    candidats = list(favoris or [])
    if not any(normaliser_nom(a.get("nom", "")) == cle for a in candidats):
        candidats += await search_async(nom)
    for a in candidats:
        if normaliser_nom(a.get("nom", "")) == cle and a.get("url"):
            _url_par_nom[cle] = a["url"]
            return a["url"]
    return ""
