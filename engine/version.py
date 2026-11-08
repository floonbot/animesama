"""Identite du paquet en cours d'execution.

APP_VERSION est le seul litteral de version du code Python : app.py et health.py
l'importent. pyproject.toml et installer.iss doivent le repeter (leurs formats
n'admettent pas d'import), un test verrouille leur accord.

build-info.json est ecrit par packaging/stamp_build.py au moment du packaging et
n'existe donc pas quand on lance les sources. C'est precisement ce qui rend
l'ecart visible : le raccourci du Bureau lance l'application *installee*, pas le
depot, et sans horodatage de build rien ne distingue un paquet d'avant-hier d'un
paquet du jour.
"""

import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("engine.version")

APP_VERSION = "2.0.0"

TAMPON_NOM = "build-info.json"


def empreinte_installation(racine: Path | None = None) -> str:
    """Distingue les installations d'une meme machine : 12 hex du chemin.

    Sources, dossier de build et application installee partagent trousseau,
    %TEMP% et port. Le chemin est replie en casse, comme Windows. Ce calcul
    nomme aussi les cles du trousseau : le changer rendrait illisible le
    cookies.enc deja sur disque.
    """
    from engine.config.settings import ROOT_DIR

    base = str(racine if racine is not None else ROOT_DIR)
    return hashlib.sha256(base.casefold().encode("utf-8")).hexdigest()[:12]


def chemin_tampon() -> Path:
    from engine.config.settings import STATIC_DIR

    return STATIC_DIR / TAMPON_NOM


def lire_tampon() -> dict[str, Any] | None:
    try:
        brut = chemin_tampon().read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(brut)
    except json.JSONDecodeError as e:
        log.warning("%s illisible (%s) — identite de build inconnue", TAMPON_NOM, e)
        return None
    return data if isinstance(data, dict) else None


def identite_build() -> dict[str, Any]:
    """source : 'sources' | 'paquet' | 'paquet_sans_tampon'.

    Un tampon laisse dans l'arbre de travail par un build precedent ne fait pas
    d'une execution des sources un paquet : hors frozen, on ne le lit meme pas.
    """
    frozen = bool(getattr(sys, "frozen", False))
    tampon = (lire_tampon() or {}) if frozen else {}
    if not frozen:
        source = "sources"
    elif tampon:
        source = "paquet"
    else:
        source = "paquet_sans_tampon"
    horodatage = tampon.get("built_at")
    if not isinstance(horodatage, int | float):
        horodatage = None
    return {
        "version": APP_VERSION,
        "source": source,
        "built_at": horodatage,
        "built_at_iso": tampon.get("built_at_iso") or "",
        "front": tampon.get("front") or "",
        "git": tampon.get("git") or "",
        "python": tampon.get("python") or "",
        # Lu par desktop.py pour ne se brancher que sur sa propre installation.
        "installation": empreinte_installation(),
    }


def _date_lisible(horodatage: float | None, iso: str) -> str:
    if horodatage:
        return time.strftime("%d/%m/%Y %H:%M", time.localtime(horodatage))
    return iso or "date inconnue"


def description_build() -> str:
    ident = identite_build()
    base = f"version {ident['version']}"
    if ident["source"] == "sources":
        return f"{base} — sources de developpement"
    if ident["source"] == "paquet_sans_tampon":
        return f"{base} — paquet sans horodatage (construit avant build-info.json)"
    date = _date_lisible(ident["built_at"], ident["built_at_iso"])
    suffixe = f" · git {ident['git']}" if ident["git"] else ""
    # L'interpreteur empaquete n'est pas celui sous lequel la suite tourne : le
    # dire ici evite d'avoir a ouvrir le diagnostic pour s'en apercevoir.
    if ident.get("python"):
        suffixe += f" · Python {ident['python']}"
    return f"{base} — paquet construit le {date}{suffixe}"
