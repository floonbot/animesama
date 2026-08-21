import json
import logging

import pytest

import engine.config.settings as settings


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    settings.invalider_downloads_dir_cache()
    settings.invalider_scans_dir_cache()
    settings._downloads_dir._default = tmp_path / "dl_default"
    settings._scans_dir._default = tmp_path / "sc_default"
    yield tmp_path
    settings.invalider_downloads_dir_cache()
    settings.invalider_scans_dir_cache()


def _configurer(tmp_data, **payload):
    (tmp_data / "user_settings.json").write_text(json.dumps(payload), encoding="utf-8")


def test_dossier_configure_supprime_est_recree(tmp_data):
    cible = tmp_data / "biblio" / "anime"
    _configurer(tmp_data, downloads_dir=str(cible))

    assert settings.get_downloads_dir() == cible
    assert cible.is_dir()


def test_dossier_configure_injoignable_est_signale(tmp_data, caplog):
    obstacle = tmp_data / "pas-un-dossier"
    obstacle.write_text("x", encoding="utf-8")
    cible = obstacle / "anime"
    _configurer(tmp_data, downloads_dir=str(cible))

    with caplog.at_level(logging.ERROR, logger="engine.config.settings"):
        resultat = settings.get_downloads_dir()

    assert resultat == settings._downloads_dir._default
    message = " ".join(r.getMessage() for r in caplog.records)
    assert str(cible) in message
    assert str(settings._downloads_dir._default) in message


def test_scans_dir_injoignable_est_signale_aussi(tmp_data, caplog):
    obstacle = tmp_data / "obstacle-scans"
    obstacle.write_text("x", encoding="utf-8")
    cible = obstacle / "scans"
    _configurer(tmp_data, scans_dir=str(cible))

    with caplog.at_level(logging.ERROR, logger="engine.config.settings"):
        resultat = settings.get_scans_dir()

    assert resultat == settings._scans_dir._default
    assert str(cible) in " ".join(r.getMessage() for r in caplog.records)


def test_alerte_non_repetee_a_chaque_appel(tmp_data, caplog):
    obstacle = tmp_data / "obstacle"
    obstacle.write_text("x", encoding="utf-8")
    _configurer(tmp_data, downloads_dir=str(obstacle / "anime"))

    with caplog.at_level(logging.ERROR, logger="engine.config.settings"):
        settings.get_downloads_dir()
        settings.invalider_downloads_dir_cache()
        settings.get_downloads_dir()

    alertes = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(alertes) == 1


def test_partage_reseau_refuse_ne_blame_pas_user_settings(tmp_data, caplog, monkeypatch):
    # Cas releve sur un partage SMB hors ligne : is_dir() sur \\SERVEUR_TEST\...
    # leve WinError 1326 (identifiants refuses). L'OSError remontait au except
    # global et le journal accusait « user_settings.json illisible ».
    from pathlib import Path

    partage = tmp_data / "partage-reseau"
    _configurer(tmp_data, downloads_dir=str(partage))

    vrai_is_dir = Path.is_dir

    def _is_dir(self, *a, **k):
        if self == partage:
            raise OSError(1326, "Le nom d'utilisateur ou le mot de passe est incorrect")
        return vrai_is_dir(self, *a, **k)

    monkeypatch.setattr(Path, "is_dir", _is_dir)

    with caplog.at_level(logging.WARNING, logger="engine.config.settings"):
        resultat = settings.get_downloads_dir()

    assert resultat == settings._downloads_dir._default
    message = " ".join(r.getMessage() for r in caplog.records)
    assert "user_settings.json illisible" not in message
    assert "inaccessible" in message
    assert str(partage) in message


def test_retour_du_dossier_reautorise_une_alerte(tmp_data, caplog):
    obstacle = tmp_data / "obstacle"
    obstacle.write_text("x", encoding="utf-8")
    cible = obstacle / "anime"
    _configurer(tmp_data, downloads_dir=str(cible))

    with caplog.at_level(logging.ERROR, logger="engine.config.settings"):
        settings.get_downloads_dir()

        obstacle.unlink()
        cible.mkdir(parents=True)
        settings.invalider_downloads_dir_cache()
        assert settings.get_downloads_dir() == cible

        import shutil
        shutil.rmtree(cible.parent)
        obstacle.write_text("x", encoding="utf-8")
        settings.invalider_downloads_dir_cache()
        settings.get_downloads_dir()

    alertes = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(alertes) == 2
