import re

from bs4 import Tag

from engine.scraping.parser._base import (
    _RE_LANG_PAREN,
    _RE_LANG_SUFFIX,
    _RE_SLUG,
    _attr_str,
    _make_soup,
    log,
)

_UI_GARBAGE = {
    "trier", "filtrer", "voir", "tous", "filter", "sort",
    "recherche", "rechercher", "catalogue", "accueil",
    "vostfr", "vf", "vo", "liste", "grille",
    "favoris", "favori", "favorites", "favorite", "mes favoris",
    "ajouter aux favoris", "retirer des favoris",
    "ajouter", "retirer",
}

_RE_BADGE = re.compile(r"badge|lang|vostfr|vf", re.I)


def _extraire_nom_resultat(a: Tag, slug: str) -> str:
    nom = ""
    parent: Tag | None = a
    for _ in range(4):
        if parent is None:  # pragma: no cover
            break
        for tag in ("h1", "h2", "h3", "h4", "p", "span"):
            el = parent.find(tag)
            if el:
                txt = el.get_text(strip=True)
                if txt and len(txt) > 2 and txt.lower() not in _UI_GARBAGE:
                    nom = txt
                    break
        if nom:
            break
        parent = parent.parent

    if not nom:
        img_el = a.find("img")
        if img_el:
            alt = _attr_str(img_el, "alt").strip()
            if alt and len(alt) > 2 and alt.lower() not in _UI_GARBAGE:
                nom = alt
        if not nom:
            nom = slug.replace("-", " ").title()

    nom = _RE_LANG_SUFFIX.sub("", nom).strip()
    nom = _RE_LANG_PAREN.sub("", nom).strip()
    return nom[:200]

def _extraire_image_resultat(a: Tag, slug: str, covers_base: str) -> str:
    img = ""
    img_el = a.find("img")
    if img_el:
        img = (
            _attr_str(img_el, "src") or
            _attr_str(img_el, "data-src") or
            _attr_str(img_el, "data-lazy-src") or
            ""
        ).strip()
    if not img:
        img = f"{covers_base}/{slug}.jpg"
    return img

def _extraire_statut_resultat(a: Tag) -> str:
    badge = a.find(class_=_RE_BADGE)
    if badge:
        return badge.get_text(strip=True).upper()
    return ""

def parse_search_results(html: str) -> list[dict]:
    from engine.scraping.site.animessama import COVERS_BASE, SITE_URL

    if not html:
        return []

    soup = _make_soup(html)
    results: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=_RE_SLUG):
        href = _attr_str(a, "href")
        if not href or href in seen:  # pragma: no cover
            continue

        m_slug = _RE_SLUG.search(href)
        if not m_slug:  # pragma: no cover
            continue

        slug = m_slug.group(1)
        if "/" in slug:  # pragma: no cover
            continue

        if slug in seen:
            continue
        seen.add(slug)
        full_url = href if href.startswith("http") else SITE_URL + href

        results.append({
            "nom": _extraire_nom_resultat(a, slug),
            "url": full_url,
            "image": _extraire_image_resultat(a, slug, COVERS_BASE),
            "statut": _extraire_statut_resultat(a),
        })

    log.debug(f"parse_search_results : {len(results)} résultats")
    return results
