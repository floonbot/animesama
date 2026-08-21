"""Le tampon de build affichait le SHA de HEAD sans dire que l'arbre était sale.

Constaté : un paquet construit le 6 août 20:41 annonçait `12e1c67` — le commit
C4 — alors qu'il embarquait le code C7/C8 non encore commité. Le tampon existe
justement pour savoir quel code tourne : sans suffixe, il ment.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

# `packaging/` du depot est masque par la distribution PyPI du meme nom :
# on charge le script par son chemin.
_SPEC = importlib.util.spec_from_file_location(
    "_stamp_build_sous_test",
    Path(__file__).resolve().parent.parent / "packaging" / "stamp_build.py",
)
assert _SPEC and _SPEC.loader
stamp_build = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(stamp_build)


class _Sortie:
    def __init__(self, code: int, texte: str) -> None:
        self.returncode = code
        self.stdout = texte
        self.stderr = ""


def _git(monkeypatch, reponses: dict[str, _Sortie]):
    appels: list[list[str]] = []

    def _run(cmd, **kwargs):
        appels.append(list(cmd))
        for motif, sortie in reponses.items():
            if motif in " ".join(cmd):
                return sortie
        return _Sortie(1, "")

    monkeypatch.setattr(subprocess, "run", _run)
    return appels


def test_arbre_propre_donne_le_sha_nu(monkeypatch):
    _git(monkeypatch, {
        "rev-parse": _Sortie(0, "12e1c67\n"),
        "status": _Sortie(0, ""),
    })

    assert stamp_build.revision_git() == "12e1c67"


def test_arbre_sale_est_signale(monkeypatch):
    _git(monkeypatch, {
        "rev-parse": _Sortie(0, "12e1c67\n"),
        "status": _Sortie(0, " M engine/version.py\n?? packaging/x.py\n"),
    })

    assert stamp_build.revision_git() == "12e1c67-dirty"


def test_git_absent_ne_casse_pas_le_build(monkeypatch):
    def _run(cmd, **kwargs):
        raise OSError("git introuvable")

    monkeypatch.setattr(subprocess, "run", _run)

    assert stamp_build.revision_git() == ""


def test_statut_illisible_ne_pretend_pas_l_arbre_propre(monkeypatch):
    _git(monkeypatch, {
        "rev-parse": _Sortie(0, "12e1c67\n"),
        "status": _Sortie(128, ""),
    })

    # Ne pas savoir n'est pas « propre » : le doute doit se voir.
    assert stamp_build.revision_git() == "12e1c67-inconnu"


def test_hors_depot_git_ne_donne_pas_de_revision(monkeypatch):
    _git(monkeypatch, {"rev-parse": _Sortie(128, "")})

    assert stamp_build.revision_git() == ""


@pytest.mark.parametrize("git,attendu", [
    ("12e1c67", "git 12e1c67"),
    ("12e1c67-dirty", "git 12e1c67-dirty"),
    ("", ""),
])
def test_la_description_reprend_le_suffixe(monkeypatch, git, attendu):
    from engine import version

    monkeypatch.setattr(version, "identite_build", lambda: {
        "version": "2.0.0", "source": "paquet", "built_at": 1_700_000_000.0,
        "built_at_iso": "2023-11-14T23:13:20", "front": "abc", "git": git,
        "python": "3.14.6",
    })

    description = version.description_build()

    if attendu:
        assert attendu in description
    else:
        assert "git" not in description
