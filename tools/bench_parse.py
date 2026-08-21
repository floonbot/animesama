"""Micro-benchmark reproductible du parsing HTML (scraping).

Compare, pour chaque parseur optimise, la fonction reelle du moteur a une
re-implementation "full-soup naive" (BeautifulSoup sans SoupStrainer) sur du
HTML representatif, en verifiant que la sortie est byte-identique avant de
chiffrer le gain.

Usage : python tools/bench_parse.py [iterations]
Aucune I/O reseau, deterministe. A lancer AVANT et APRES une optimisation.
"""

import os
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

from engine.scraping.parser._base import _STRAINER_EP_NAMES, _make_soup
from engine.scraping.parser.episodes import (
    _extraire_titre_episodes,
    _nb_episodes_depuis_options,
    parse_saisons,
)
from engine.scraping.parser.profile import detecter_type_contenu


def _profile_html(n_fav: int = 300, n_links: int = 400, filler_kb: int = 120) -> str:
    favs = ",".join(
        f'{{"url":"/catalogue/anime-{i}","name":"Anime {i}","img":"https://cdn/{i}.jpg"}}'
        for i in range(n_fav)
    )
    script = f'<script>window.ASN_PROFIL = {{"library":{{"favorites":[{favs}]}}}};</script>'
    links = "".join(
        f'<a href="/catalogue/anime-{i}/saison1/vostfr"><div class="card"><h2>Anime {i}</h2>'
        f'<img src="https://cdn/{i}.jpg" alt="Anime {i}"></div></a>'
        for i in range(n_links)
    )
    filler = '<div class="x"><span>lorem ipsum dolor sit amet </span></div>' * (
        filler_kb * 1024 // 60
    )
    return f"<html><head>{script}</head><body>{links}{filler}</body></html>"


def _catalogue_html(n_saisons: int = 12, n_noise_links: int = 400, filler_kb: int = 120) -> str:
    saisons = "".join(
        f'<a href="/catalogue/mon-anime/saison{n}/vostfr">Saison {n} VOSTFR</a>'
        f'<a href="/catalogue/mon-anime/saison{n}/vf">Saison {n} VF</a>'
        for n in range(1, n_saisons + 1)
    )
    noise = "".join(f'<a href="/autre/{i}">lien {i}</a>' for i in range(n_noise_links))
    filler = '<div class="x"><span>lorem ipsum dolor sit amet </span></div>' * (
        filler_kb * 1024 // 60
    )
    return f"<html><body>{saisons}{noise}{filler}</body></html>"


def _season_html(n_opt: int = 12, n_noise: int = 4000, filler_kb: int = 80) -> str:
    opts = "".join(f"<option>Episode {i}</option>" for i in range(n_opt))
    noise = '<div class="card"><span>bla</span><a href="/x">y</a></div>' * n_noise
    filler = '<div class="x"><span>lorem ipsum dolor sit amet </span></div>' * (
        filler_kb * 1024 // 60
    )
    eps = ",".join(f'"u{i}"' for i in range(n_opt))
    return (
        f'<html><head><title>Anime-Sama - Mon Anime</title></head><body>'
        f'<h1 id="titreOeuvre">Mon Anime</h1>{noise}{filler}'
        f'<select id="selectEpisodes">{opts}</select>'
        f'<script>var eps1=[{eps}]</script></body></html>'
    )


def _engine_episode_meta(html: str) -> tuple:
    soup = _make_soup(html, parse_only=_STRAINER_EP_NAMES)
    return _extraire_titre_episodes(html, soup), _nb_episodes_depuis_options(soup)


def _naive_episode_meta(html: str) -> tuple:
    soup = BeautifulSoup(html or "", "lxml")
    el = soup.find(id="titreOeuvre")
    titre = el.get_text(strip=True) if el else ""
    if not titre:
        t = soup.find("title")
        if t:
            titre = t.get_text(strip=True).replace("Anime-Sama - ", "").strip()
    titre = titre[:200] if titre else ""
    sel = soup.find("select", id="selectEpisodes")
    nb = len(sel.find_all("option")) if sel else 0
    return titre, nb


def _naive_saisons(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    return len(soup.find_all("a", href=True))


def _naive_type(html: str) -> dict:
    import re

    soup = BeautifulSoup(html, "lxml")
    has_anime = has_scan = False
    for a in soup.find_all("a", href=True):
        raw = a.get("href")
        href = (raw if isinstance(raw, str) else "").lower()
        if "/saison" in href:
            has_anime = True
        if re.search(r"/scan(\d*)/", href) or href.endswith("/scan"):
            has_scan = True
    return {"has_anime": has_anime, "has_scan": has_scan}


def _timeit(fn, n: int) -> float:
    fn()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n * 1000


def _peak_kb(fn) -> float:
    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 1024


def _bench(name: str, engine_fn, naive_fn, html: str, n: int, equiv: bool) -> None:
    eng = engine_fn(html)
    if equiv:
        nai = naive_fn(html)
        ok = (eng == nai) if not isinstance(eng, dict) else (eng == nai)
        flag = "OK" if ok else "MISMATCH"
    else:
        flag = "(naive=ref)"
    t_eng = _timeit(lambda: engine_fn(html), n)
    t_nai = _timeit(lambda: naive_fn(html), n)
    speed = t_nai / t_eng if t_eng else 0.0
    m_eng = _peak_kb(lambda: engine_fn(html))
    m_nai = _peak_kb(lambda: naive_fn(html))
    mem = m_nai / m_eng if m_eng else 0.0
    print(
        f"{name:<26} engine={t_eng:7.2f}ms  full-soup={t_nai:7.2f}ms  x{speed:4.2f}  | "
        f"mem engine={m_eng:7.0f}Ko full-soup={m_nai:7.0f}Ko x{mem:4.2f}  [{flag}]"
    )


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    prof = _profile_html()
    cata = _catalogue_html()
    saison = _season_html()
    print(
        f"profile html = {len(prof)//1024} Ko | catalogue html = {len(cata)//1024} Ko | "
        f"saison html = {len(saison)//1024} Ko | iter={n}\n"
    )
    _bench("parse_saisons", lambda h: len(parse_saisons(h)), _naive_saisons, cata, n, equiv=False)
    _bench("detecter_type_contenu", detecter_type_contenu, _naive_type, prof, n, equiv=True)
    _bench("parse_episodes_meta", _engine_episode_meta, _naive_episode_meta, saison, n, equiv=True)


if __name__ == "__main__":
    main()
