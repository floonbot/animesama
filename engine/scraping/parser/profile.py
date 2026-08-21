import re
from urllib.parse import urlparse

from engine.scraping.parser._base import (
    _RE_SLUG,
    _STRAINER_A,
    _attr_str,
    _make_soup,
    log,
)

_RE_SCAN = re.compile(r"/scan(\d*)/")

# Le compte anime-sama tient quatre listes ; get-data.php les nomme en toutes
# lettres, pas comme les onglets de /profil (`fav`, `watch`, `vu`, `histo`).
# `favorites`, `watchlist` et `viewed` sont trois dicts de tableaux paralleles
# de meme forme ; `history` porte en plus type/lang/ep et ses URL designent une
# saison, d'ou la reduction a l'oeuvre.
_LISTES: tuple[tuple[str, str], ...] = (
    ("favorites", "favoris"),
    ("watchlist", "watchlist"),
    ("viewed", "vus"),
    ("history", "historique"),
)

def _url_netloc(u: str) -> str:
    try:
        return urlparse(u).netloc.lower()
    except ValueError:
        return ""


def _absolutiser(url: str) -> str:
    from engine.scraping.site.animessama import SITE_URL

    u = (url or "").strip()
    if not u:
        return ""
    if not u.startswith("http"):
        u = SITE_URL + "/" + u.lstrip("/")
    return u

# Sans cette reduction, un anime vu en saison 2 formerait une entree distincte
# du meme anime present dans les favoris. Sans reste de chemin, l'URL d'origine
# est rendue telle quelle : la barre finale des favoris n'est pas normalisee.
def _reduire_a_l_oeuvre(url: str) -> str:
    from engine.scraping.site.animessama import SITE_URL

    m = _RE_SLUG.search(url)
    if not m:
        return url
    reste = url[m.end():].lstrip("/").split("?", 1)[0].split("#", 1)[0]
    if not reste:
        return url
    return f"{SITE_URL}/catalogue/{m.group(1)}/"

def _cle_oeuvre(url: str) -> str:
    m = _RE_SLUG.search(url)
    return m.group(1).lower() if m else url.rstrip("/").lower()

def _fusionner(
    index: dict[str, dict], ordre: list[dict], nom: str, url_brute: str, img: str, liste: str
) -> None:
    from engine.scraping.site.animessama import COVERS_BASE, SITE_URL

    url = _absolutiser(url_brute)
    if not url or _url_netloc(url) != _url_netloc(SITE_URL):
        return
    url = _reduire_a_l_oeuvre(url)

    entree = index.get(_cle_oeuvre(url))
    if entree is None:
        if not img:
            m = _RE_SLUG.search(url)
            if m:
                img = f"{COVERS_BASE}/{m.group(1)}.jpg"
        entree = {
            "nom": nom or url.rstrip("/").split("/")[-1],
            "url": url,
            "image": img,
            "statut": "",
            "type": "anime",
            "listes": [],
        }
        index[_cle_oeuvre(url)] = entree
        ordre.append(entree)
    if liste not in entree["listes"]:
        entree["listes"].append(liste)

def parse_favoris_api(data: dict) -> list[dict]:
    if not isinstance(data, dict):
        return []

    index: dict[str, dict] = {}
    ordre: list[dict] = []
    for cle_api, liste in _LISTES:
        bloc = data.get(cle_api)
        if not isinstance(bloc, dict):
            continue
        urls = bloc.get("url")
        if not isinstance(urls, list):
            continue
        noms = bloc.get("nom")
        if not isinstance(noms, list):
            noms = []
        imgs = bloc.get("img")
        if not isinstance(imgs, list):
            imgs = []

        for i, url in enumerate(urls):
            if not isinstance(url, str):
                continue
            nom = noms[i].strip() if i < len(noms) and isinstance(noms[i], str) else ""
            img = imgs[i].strip() if i < len(imgs) and isinstance(imgs[i], str) else ""
            _fusionner(index, ordre, nom, url, img, liste)

    log.debug(f"parse_favoris_api : {len(ordre)} oeuvre(s) sur {len(_LISTES)} listes")
    return ordre

def detecter_type_contenu(html: str) -> dict:
    if not html:
        return {"has_anime": False, "has_scan": False}

    has_anime = "panneauAnime(" in html
    has_scan = "panneauScan(" in html
    if has_anime or has_scan:
        return {"has_anime": has_anime, "has_scan": has_scan}

    soup = _make_soup(html, parse_only=_STRAINER_A)

    for a in soup.find_all("a", href=True):
        href = _attr_str(a, "href").lower()
        if "/saison" in href:
            has_anime = True
        if _RE_SCAN.search(href) or href.endswith("/scan"):
            has_scan = True
        if has_anime and has_scan:
            break

    return {"has_anime": has_anime, "has_scan": has_scan}
