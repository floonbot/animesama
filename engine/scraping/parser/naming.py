import re

from engine.scraping.parser._base import _RE_INVALID_FS

_RE_SAISON_NOM = re.compile(r"^\s*saison\s*0*(\d+)\s*$", re.I)


def nettoyer_titre(titre: str) -> str:
    t = re.sub(r'\s+(?:Season|Saison|Part)\s+\d+\s*$', "", (titre or "").strip(), flags=re.I)
    t = _RE_INVALID_FS.sub("", t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = t.strip(" .")
    return t[:100] or "Anime"

def _nettoyer_segment(nom: str, limite: int) -> str:
    seg = _RE_INVALID_FS.sub("", (nom or "").strip())
    seg = re.sub(r'\s+', ' ', seg).strip(" .")
    return seg[:limite]

def dossier_saison(saison_nom: str = "", saison: int = 1) -> str:
    nom = (saison_nom or "").strip()
    m = _RE_SAISON_NOM.match(nom)
    if m:
        return f"Saison {int(m.group(1)):02d}"
    if nom:
        return _nettoyer_segment(nom, 80) or "Saison 01"
    try:
        return f"Saison {int(saison):02d}"
    except (TypeError, ValueError):
        return "Saison 01"

def nom_fichier(titre: str, saison: int, episode: int, langue: str = "", saison_nom: str = "") -> str:
    try:
        episode_n = int(episode)
    except (TypeError, ValueError):
        episode_n = 0

    t = _RE_INVALID_FS.sub("", (titre or "").strip()).strip(" .")

    nom_s = (saison_nom or "").strip()
    m = _RE_SAISON_NOM.match(nom_s)
    if nom_s and not m:
        nom = f"{t} - {_nettoyer_segment(nom_s, 60)} - E{episode_n:03d}"
    else:
        try:
            saison_n = int(m.group(1)) if m else int(saison)
        except (TypeError, ValueError):
            saison_n = 1
        nom = f"{t} - S{saison_n:02d}E{episode_n:03d}"

    lang_up = (langue or "").strip().upper()
    if lang_up and not re.search(r'\b' + re.escape(lang_up) + r'\b', nom):
        nom = f"{nom} {lang_up}"

    return nom.strip()
