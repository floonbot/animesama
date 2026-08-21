"""Premier lancement sur une machine vierge : l'app doit démarrer et dire ce qui
manque, pas mourir sur une trace Python.

- data/ et covers_cache/ étaient créés par un mkdir nu au niveau module : sur une
  installation en lecture seule, l'import de engine.config.settings levait une
  OSError et *tous* les points d'entrée mouraient sans message.
- aucun bilan des binaires au démarrage : sans yt-dlp ni ffmpeg (log.debug),
  l'utilisateur ne l'apprenait qu'au premier téléchargement raté.
"""

import logging
from pathlib import Path

import pytest

import server
from engine.config import settings


def test_data_dir_illisible_ne_tue_pas_l_import(monkeypatch, caplog):
    def _refuse(self, *a, **k):
        raise PermissionError("accès refusé")

    monkeypatch.setattr(Path, "mkdir", _refuse)

    with caplog.at_level(logging.ERROR, logger="engine.config.settings"):
        settings._preparer_data_dir(Path("Z:/inexistant/data"))

    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "donnees" in msgs
    assert "droits" in msgs


def test_data_dir_normal_est_cree(tmp_path):
    cible = tmp_path / "data"
    settings._preparer_data_dir(cible)
    assert cible.is_dir()


def test_cache_jaquettes_illisible_ne_tue_pas_l_import(monkeypatch, caplog):
    from engine.cache import cover_images

    def _refuse(self, *a, **k):
        raise PermissionError("accès refusé")

    monkeypatch.setattr(Path, "mkdir", _refuse)

    with caplog.at_level(logging.WARNING, logger="engine.cache.cover_images"):
        cover_images._preparer_cache_dir(Path("Z:/inexistant/covers"))

    assert any("jaquette" in r.getMessage().lower() for r in caplog.records)


def test_aucun_moteur_present_est_signale_bruyamment(monkeypatch, caplog):
    monkeypatch.setattr(server, "_moteurs_presents", lambda: {})

    with caplog.at_level(logging.ERROR, logger="main"):
        manquants = server.verifier_prerequis()

    assert manquants
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "N_m3u8DL-RE" in msgs
    assert "yt-dlp" in msgs
    assert "ffmpeg" in msgs


def test_moteur_partiel_est_signale_sans_bloquer(monkeypatch, caplog):
    monkeypatch.setattr(
        server, "_moteurs_presents",
        lambda: {"nm3u8dl": "C:/bin/N_m3u8DL-RE.exe", "ytdlp": None, "ffmpeg": None},
    )

    with caplog.at_level(logging.WARNING, logger="main"):
        manquants = server.verifier_prerequis()

    assert manquants == ["yt-dlp", "ffmpeg"]
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_tout_present_ne_dit_rien(monkeypatch, caplog):
    monkeypatch.setattr(
        server, "_moteurs_presents",
        lambda: {"nm3u8dl": "a", "ytdlp": "b", "ffmpeg": "c"},
    )

    with caplog.at_level(logging.WARNING, logger="main"):
        assert server.verifier_prerequis() == []

    assert caplog.records == []


def test_verifier_prerequis_ne_leve_jamais(monkeypatch):
    def _boum():
        raise RuntimeError("sonde cassée")

    monkeypatch.setattr(server, "_moteurs_presents", _boum)
    assert server.verifier_prerequis() == []


@pytest.mark.parametrize("moteur", ["nm3u8dl", "ytdlp", "ffmpeg"])
def test_les_sondes_de_moteur_repondent(moteur):
    assert moteur in server._moteurs_presents()
