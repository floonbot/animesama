"""Regression : sous Windows les trois moteurs écrivent le fichier sous le nom
raccourci par borner_nom_fichier, mais fichier_existe le cherchait sous le nom
complet. Conséquence : skip_existants ne voyait jamais un épisode à titre long,
et l'app le re-téléchargeait à chaque passage.
"""

import os

import pytest

from engine.download import _engine_utils as eu
from engine.download import _helpers as helpers

TITRE_LONG = "Un Titre D Anime Vraiment Tres Long Qui Sature Le Chemin " * 4


@pytest.fixture
def sous_windows(monkeypatch):
    monkeypatch.setattr(eu.os, "name", "nt")


@pytest.fixture
def petit_seuil(monkeypatch):
    monkeypatch.setattr(helpers, "TAILLE_MIN_FICHIER", 8)


def _dossier_profond(tmp_path):
    d = tmp_path / "downloads" / "Un Titre D Anime Assez Long" / "Saison 01"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def test_fichier_deja_telecharge_est_detecte_malgre_le_raccourcissement(
    sous_windows, petit_seuil, tmp_path
):
    dossier = _dossier_profond(tmp_path)
    nom_complet = f"{TITRE_LONG[:200]} - S01E001 VOSTFR"
    nom_ecrit = eu.borner_nom_fichier(dossier, nom_complet, ".mp4")
    assert nom_ecrit != nom_complet

    with open(os.path.join(dossier, nom_ecrit + ".mp4"), "wb") as f:
        f.write(b"x" * 4096)

    assert helpers.fichier_existe(dossier, nom_complet) is not None


def test_reprise_en_cours_bloque_le_skip_malgre_le_raccourcissement(
    sous_windows, petit_seuil, tmp_path
):
    dossier = _dossier_profond(tmp_path)
    nom_complet = f"{TITRE_LONG[:200]} - S01E002 VOSTFR"
    nom_ecrit = eu.borner_nom_fichier(dossier, nom_complet, ".mp4")

    with open(os.path.join(dossier, nom_ecrit + ".mp4"), "wb") as f:
        f.write(b"x" * 4096)
    os.makedirs(os.path.join(dossier, "_tmp_" + nom_ecrit), exist_ok=True)

    assert helpers.fichier_existe(dossier, nom_complet) is None


def test_nom_court_inchange(petit_seuil, tmp_path):
    dossier = _dossier_profond(tmp_path)
    nom = "Cowboy Bebop - S01E001 VOSTFR"
    with open(os.path.join(dossier, nom + ".mkv"), "wb") as f:
        f.write(b"x" * 4096)

    assert helpers.fichier_existe(dossier, nom) is not None


def test_fichier_absent_reste_absent(sous_windows, petit_seuil, tmp_path):
    dossier = _dossier_profond(tmp_path)
    assert helpers.fichier_existe(dossier, f"{TITRE_LONG[:200]} - S01E003 VF") is None
