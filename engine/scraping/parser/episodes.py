import re

from bs4 import BeautifulSoup

from engine.scraping.parser._base import (
    _RE_LANG_URL,
    _RE_SAISON_NUM,
    _STRAINER_A,
    _STRAINER_EP_NAMES,
    _STRAINER_TITREOEUVRE,
    _attr_str,
    _extraire_eps_arrays,
    _make_soup,
    log,
)

_RE_SECTION_OU_PANNEAU = re.compile(
    r'<h2[^>]*>(.*?)</h2>'
    r'|panneauAnime\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)',
    re.I | re.S,
)
_RE_TAGS_H2 = re.compile(r"<[^>]+>")


def parse_panneaux(html: str) -> list[dict]:
    brut: list[tuple[str, str, str, str]] = []
    section = ""
    for m in _RE_SECTION_OU_PANNEAU.finditer(html or ""):
        if m.group(1) is not None:
            section = _RE_TAGS_H2.sub("", m.group(1)).strip()
            continue
        path = (m.group(3) or "").strip().strip("/")
        if not path or path.lower() == "url":
            continue
        parts = path.split("/")
        seg = parts[0].strip()
        if not seg:
            continue
        lang = parts[1].strip().lower() if len(parts) > 1 and parts[1].strip() else "vostfr"
        brut.append((m.group(2).strip(), seg, lang, section))

    sections_ordre: list[str] = []
    for _, _, _, sec in brut:
        if sec not in sections_ordre:
            sections_ordre.append(sec)
    section_primaire = sections_ordre[0] if sections_ordre else ""
    multi = len(sections_ordre) > 1

    out: list[dict] = []
    seen: set[str] = set()
    for label, seg, lang, sec in brut:
        key = seg.lower()
        if key in seen:
            continue
        seen.add(key)
        nom = f"{sec} - {label}" if multi and sec and sec != section_primaire else label
        out.append({"nom": nom, "seg": seg, "lang": lang})
    log.debug(f"parse_panneaux : {len(out)} panneau(x) anime, {len(sections_ordre)} section(s)")
    return out


def parse_saisons(html: str) -> list[dict]:
    from engine.scraping.site.animessama import SITE_URL

    soup = _make_soup(html, parse_only=_STRAINER_A)
    saisons: list[dict] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=_RE_SAISON_NUM):
        href = _attr_str(a, "href")
        if not href or href in seen:
            continue
        seen.add(href)

        m_saison = _RE_SAISON_NUM.search(href)
        m_lang = _RE_LANG_URL.search(href)
        if not m_saison:  # pragma: no cover
            continue

        num = int(m_saison.group(1))
        lang = m_lang.group(1).lower() if m_lang else "vostfr"
        full = href if href.startswith("http") else SITE_URL + "/" + href.lstrip("/")

        saisons.append({"saison": num, "url": full, "lang": lang})

    saisons.sort(key=lambda x: x["saison"])
    log.debug(f"parse_saisons : {len(saisons)} saisons trouvées")
    return saisons

def _nb_episodes_depuis_options(soup: BeautifulSoup) -> int:
    sel = soup.find("select", id="selectEpisodes")
    if not sel:
        return 0
    return len(sel.find_all("option"))

def _extraire_titre_episodes(html: str, soup_names: BeautifulSoup) -> str:
    titre = ""
    if "titreOeuvre" in html:
        el = _make_soup(html, parse_only=_STRAINER_TITREOEUVRE).find(id="titreOeuvre")
        if el:
            titre = el.get_text(strip=True)
    if not titre:
        t = soup_names.find("title")
        if t:
            titre = t.get_text(strip=True).replace("Anime-Sama - ", "").strip()
    return titre[:200] if titre else ""

def _determiner_nb_episodes(nb_ep_arrays: int, nb_ep_select: int) -> int:
    nb_ep = max(nb_ep_arrays, nb_ep_select)
    if nb_ep_arrays and 0 < (nb_ep_select - nb_ep_arrays) <= 3:
        log.info(
            f"parse_episodes : {nb_ep_select - nb_ep_arrays} option(s) sans lecteur "
            f"ignorée(s) (select={nb_ep_select}, lecteurs={nb_ep_arrays})"
        )
        nb_ep = nb_ep_arrays
    elif nb_ep_arrays and nb_ep_select and nb_ep_arrays != nb_ep_select:
        log.info(
            f"parse_episodes : arrays={nb_ep_arrays} eps, "
            f"select={nb_ep_select} eps → max={nb_ep} "
            f"(écart large, série en cours probable)"
        )
    elif nb_ep_arrays:
        log.debug(f"parse_episodes : nb_ep={nb_ep} depuis eps[] arrays")
    elif nb_ep_select:
        log.debug(f"parse_episodes : nb_ep={nb_ep} depuis #selectEpisodes")
    return nb_ep

def parse_episodes(html: str, saison_url: str) -> dict:
    from engine.scraping.site.animessama import SITE_URL

    empty = {"titre": "", "episodes": [], "langues": [], "total": 0}
    if not html:
        return empty

    soup = _make_soup(html, parse_only=_STRAINER_EP_NAMES)

    titre = _extraire_titre_episodes(html, soup)

    m_lang = _RE_LANG_URL.search(saison_url)
    lang_str = m_lang.group(1).upper() if m_lang else "VOSTFR"

    m_saison = _RE_SAISON_NUM.search(saison_url)
    saison_num = int(m_saison.group(1)) if m_saison else 1

    eps_arrays_raw = _extraire_eps_arrays(html)
    nb_ep_arrays = max(len(v) for v in eps_arrays_raw.values()) if eps_arrays_raw else 0
    nb_ep_select = _nb_episodes_depuis_options(soup)
    nb_ep = _determiner_nb_episodes(nb_ep_arrays, nb_ep_select)

    if nb_ep == 0:
        log.warning(f"parse_episodes : 0 épisodes détectés ({saison_url[:60]})")
        return {**empty, "titre": titre}

    if nb_ep > 2000:
        log.warning(f"parse_episodes : {nb_ep} épisodes détectés — suspect, tronqué à 2000")
        nb_ep = 2000

    base = saison_url.split("?")[0].rstrip("/")
    if not base.startswith("http"):
        base = SITE_URL + "/" + base.lstrip("/")

    episodes: list[dict] = []
    for i in range(1, nb_ep + 1):
        episodes.append({
            "url": f"{base}?ep={i}",
            "saison": saison_num,
            "episode": i,
            "titre": titre,
            "langue": lang_str,
        })

    log.debug(f"parse_episodes : {titre} — {nb_ep} épisodes (S{saison_num} {lang_str})")
    return {
        "titre": titre,
        "episodes": episodes,
        "langues": [lang_str],
        "total": nb_ep,
    }
