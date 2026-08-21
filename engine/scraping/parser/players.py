from urllib.parse import urlparse

from engine.scraping.parser._base import _est_url_placeholder, _extraire_eps_arrays, log


def parse_lecteurs(html: str, ep_num: int) -> list[dict]:
    return lecteurs_depuis_arrays(_extraire_eps_arrays(html), ep_num)


def lecteurs_depuis_arrays(eps_arrays: dict[str, list[str]], ep_num: int) -> list[dict]:
    if not eps_arrays:
        log.warning("parse_lecteurs : aucun tableau eps trouvé dans le HTML")
        return []

    try:
        ep_num = int(ep_num)
    except (TypeError, ValueError):
        ep_num = 1
    if ep_num < 1:
        ep_num = 1

    idx = ep_num - 1
    lecteurs: list[dict] = []

    for var_name in sorted(eps_arrays.keys(), key=lambda n: (len(n), n)):
        urls = eps_arrays[var_name]
        if idx < 0 or idx >= len(urls):
            log.debug(f"{var_name} : index {idx} hors limites (longueur {len(urls)})")
            continue
        src = urls[idx]
        if _est_url_placeholder(src):
            continue
        try:
            host = urlparse(src).hostname or "Inconnu"
        except Exception:
            host = "Inconnu"
        lecteurs.append({"host": host, "src": src})

    log.debug(f"parse_lecteurs ep{ep_num} : {[l['host'] for l in lecteurs]}")
    return lecteurs
