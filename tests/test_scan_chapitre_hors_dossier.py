"""Regression : le numero de chapitre voyage brut du corps HTTP jusqu'a
`os.path.join(dossier, f"Chapitre {chap}.cbz")`. Aucun des trois maillons
(route, service, worker) ne l'assainit, alors que `nom` et `oeuvre` le sont.
Un chapitre contenant un separateur fait donc ecrire le .cbz hors du dossier
de scans — verifie empiriquement sous Windows : « /../../evasion » remonte de
deux niveaux.
"""

import os
from pathlib import Path

import pytest

from engine.download.methods import images

CHAPITRES_HOSTILES = ["/../../evasion", "../evasion2", "sous/dossier"]


@pytest.fixture
def sans_reseau(monkeypatch):
    monkeypatch.setattr(
        images, "_telecharger_image", lambda session, url, cache=None: (b"jpegdata", ".jpg")
    )
    monkeypatch.setattr(
        "engine.scraping.scan.get_pages_sync",
        lambda oeuvre, chap, lang: [{"page": 1, "url": "https://exemple.test/1.jpg"}],
    )


def _dossier_scan(tmp_path):
    d = tmp_path / "scans" / "Oeuvre" / "Scan VF"
    d.mkdir(parents=True)
    return d


@pytest.mark.parametrize("chap", CHAPITRES_HOSTILES)
def test_le_cbz_reste_dans_le_dossier_de_scans(sans_reseau, tmp_path, chap):
    dossier = _dossier_scan(tmp_path)

    images.scan_download("Oeuvre", "vf", [chap], str(dossier))

    ecrits = [p for p in tmp_path.rglob("*.cbz")]
    assert ecrits, "aucun chapitre ecrit"
    for p in ecrits:
        assert p.parent == dossier, f"{p} ecrit hors de {dossier}"


def test_chapitre_normal_garde_son_nom(sans_reseau, tmp_path):
    dossier = _dossier_scan(tmp_path)

    res = images.scan_download("Oeuvre", "vf", ["10.5"], str(dossier))

    assert res == str(dossier / "Chapitre 10.5.cbz")
    assert Path(res).is_file()


def test_chapitre_deja_present_est_saute(sans_reseau, tmp_path, monkeypatch):
    dossier = _dossier_scan(tmp_path)
    (dossier / "Chapitre 7.cbz").write_bytes(b"deja la")

    def _interdit(*a, **k):
        raise AssertionError("le chapitre present ne doit pas etre retelecharge")

    monkeypatch.setattr(images, "_ecrire_cbz_chapitre", _interdit)

    res = images.scan_download("Oeuvre", "vf", ["7"], str(dossier))

    assert res == str(dossier / "Chapitre 7.cbz")
    assert os.path.getsize(res) == len(b"deja la")
