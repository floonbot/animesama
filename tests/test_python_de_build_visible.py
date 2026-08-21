"""Le paquet embarque l'interpréteur qui a lancé PyInstaller ; la suite tourne
sous un autre. `py -3` résout vers le Python par défaut de la machine — 3.14 ici
— alors que pytest tourne en 3.13. L'écart est assumé : il doit au moins se voir,
dans le tampon, au démarrage et dans le diagnostic.
"""

import importlib.util
import platform
import sys
from pathlib import Path

import engine.version as version_mod

ROOT = Path(__file__).resolve().parent.parent
DIAG_JS = ROOT / "web" / "static" / "js" / "pages" / "diag.js"

_SPEC = importlib.util.spec_from_file_location(
    "_stamp_build_python", ROOT / "packaging" / "stamp_build.py"
)
assert _SPEC and _SPEC.loader
stamp_build = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(stamp_build)


def test_le_tampon_note_l_interpreteur_qui_a_construit():
    tampon = stamp_build.construire_tampon(maintenant=1_700_000_000.0)

    assert tampon["python"] == platform.python_version()


def test_identite_build_expose_le_python_du_paquet(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(version_mod, "lire_tampon", lambda: {
        "built_at": 1_700_000_000.0, "built_at_iso": "x", "front": "abc",
        "git": "1b80b3d", "python": "3.14.6",
    })

    assert version_mod.identite_build()["python"] == "3.14.6"


def test_identite_build_sans_python_dans_le_tampon(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(version_mod, "lire_tampon", lambda: {"built_at": 1.0})

    assert version_mod.identite_build()["python"] == ""


def test_la_ligne_de_demarrage_annonce_le_python_du_paquet(monkeypatch):
    monkeypatch.setattr(version_mod, "identite_build", lambda: {
        "version": "2.0.0", "source": "paquet", "built_at": 1_700_000_000.0,
        "built_at_iso": "2023-11-14T23:13:20", "front": "abc",
        "git": "1b80b3d", "python": "3.14.6",
    })

    assert "Python 3.14.6" in version_mod.description_build()


def test_les_sources_n_annoncent_pas_de_python_de_build(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert "Python" not in version_mod.description_build()


def test_le_diagnostic_affiche_le_python_du_paquet():
    src = DIAG_JS.read_text(encoding="utf-8")
    debut = src.index("function libelleBuild")
    corps = src[debut:src.index("function render", debut)]

    assert "b.python" in corps
