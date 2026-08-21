import os

import pytest

from engine.download import _engine_utils as eu

TITRE_LONG = "Un Titre D Anime Vraiment Tres Long Qui Sature Le Chemin " * 4


@pytest.fixture
def sous_windows(monkeypatch):
    monkeypatch.setattr(eu.os, "name", "nt")


def _dossier_profond(tmp_path):
    # Profondeur realiste : le dossier seul tient sous la limite, c'est le nom
    # de fichier qui la fait sauter.
    d = tmp_path / "downloads" / "Un Titre D Anime Assez Long" / "Saison 01"
    reste = 150 - len(str(d))
    if reste > 0:
        d = d / ("z" * min(reste, 40))
    return str(d)


def test_chemin_trop_long_est_raccourci(sous_windows, tmp_path):
    dossier = _dossier_profond(tmp_path)
    nom = f"{TITRE_LONG[:200]} - S01E001 VOSTFR"

    court = eu.borner_nom_fichier(dossier, nom, ".mp4")

    assert len(os.path.join(dossier, court + ".mp4")) < 260
    assert court.endswith("S01E001 VOSTFR")


def test_le_suffixe_discriminant_est_preserve(sous_windows, tmp_path):
    dossier = _dossier_profond(tmp_path)

    a = eu.borner_nom_fichier(dossier, f"{TITRE_LONG[:200]} - S01E001 VOSTFR", ".mp4")
    b = eu.borner_nom_fichier(dossier, f"{TITRE_LONG[:200]} - S01E002 VOSTFR", ".mp4")

    assert a != b
    assert a.endswith("S01E001 VOSTFR")
    assert b.endswith("S01E002 VOSTFR")


def test_suffixe_sans_saison_preserve(sous_windows, tmp_path):
    dossier = _dossier_profond(tmp_path)
    nom = f"{TITRE_LONG[:200]} - Arc Final - E042 VF"

    court = eu.borner_nom_fichier(dossier, nom, ".mp4")

    assert court.endswith("E042 VF")
    assert len(os.path.join(dossier, court + ".mp4")) < 260


def test_nom_court_inchange(sous_windows, tmp_path):
    nom = "Cowboy Bebop - S01E001 VOSTFR"

    assert eu.borner_nom_fichier(str(tmp_path), nom, ".mp4") == nom


def test_hors_windows_aucun_raccourcissement(monkeypatch, tmp_path):
    monkeypatch.setattr(eu.os, "name", "posix")
    dossier = _dossier_profond(tmp_path)
    nom = f"{TITRE_LONG[:200]} - S01E001 VOSTFR"

    assert eu.borner_nom_fichier(dossier, nom, ".mp4") == nom


def test_un_warning_est_logge(sous_windows, tmp_path, caplog):
    import logging

    dossier = _dossier_profond(tmp_path)
    nom = f"{TITRE_LONG[:200]} - S01E001 VOSTFR"

    with caplog.at_level(logging.WARNING):
        eu.borner_nom_fichier(dossier, nom, ".mp4")

    assert any("raccourci" in r.message.lower() for r in caplog.records)


def test_dossier_seul_trop_long_ne_leve_pas(sous_windows, tmp_path):
    d = tmp_path
    for i in range(8):
        d = d / f"sous-dossier-vraiment-tres-long-numero-{i:02d}"

    court = eu.borner_nom_fichier(str(d), f"{TITRE_LONG[:200]} - S01E001 VOSTFR", ".mp4")

    assert court
    assert court.endswith("S01E001 VOSTFR")


def test_les_trois_moteurs_bornent_le_nom():
    import inspect

    from engine.download.methods import _ytdlp_parsing as yp
    from engine.download.methods import ffmpeg_engine, nm3u8dl

    assert "borner_nom_fichier" in inspect.getsource(nm3u8dl._preparer_nm3u8dl)
    assert "borner_nom_fichier" in inspect.getsource(yp.construire_commande)
    assert "borner_nom_fichier" in inspect.getsource(ffmpeg_engine)
