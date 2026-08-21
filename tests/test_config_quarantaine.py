"""Un fichier de configuration illisible ne doit pas etre ecrase en silence.

Avant : load_settings() rendait les valeurs par defaut sur un JSON tronque, et
le save_settings() suivant reecrivait le fichier — dossier de telechargement,
qualite et langue perdus sans trace.
"""

import json

import pytest

from engine.config import user_settings
from engine.config._quarantaine import MAX_ECARTS, mettre_a_lecart


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", tmp_path / "user_settings.json")
    monkeypatch.setattr(user_settings, "_target", lambda: tmp_path / "user_settings.json")
    return tmp_path


def test_reglages_tronques_sont_mis_a_lecart(data_dir, caplog):
    fichier = data_dir / "user_settings.json"
    fichier.write_text('{"downloads_dir": "D:/Animes", "qual', encoding="utf-8")

    s = user_settings.load_settings()

    assert s == user_settings.DEFAULT_SETTINGS
    assert not fichier.exists()
    ecarte = data_dir / "user_settings.json.corrupt"
    assert ecarte.exists()
    assert "D:/Animes" in ecarte.read_text(encoding="utf-8")


def test_la_sauvegarde_suivante_n_ecrase_plus_l_original(data_dir):
    fichier = data_dir / "user_settings.json"
    fichier.write_text('{"downloads_dir": "D:/Animes"', encoding="utf-8")

    user_settings.load_settings()
    user_settings.save_settings({"qualite": "720"})

    # Le nouveau fichier existe, et l'ancien contenu est toujours la a cote.
    assert json.loads(fichier.read_text(encoding="utf-8"))["qualite"] == "720"
    assert "D:/Animes" in (data_dir / "user_settings.json.corrupt").read_text(encoding="utf-8")


def test_un_contenu_du_mauvais_type_est_aussi_mis_a_lecart(data_dir):
    fichier = data_dir / "user_settings.json"
    fichier.write_text('["pas", "un", "objet"]', encoding="utf-8")

    assert user_settings.load_settings() == user_settings.DEFAULT_SETTINGS
    assert (data_dir / "user_settings.json.corrupt").exists()


def test_une_erreur_d_e_s_ne_met_rien_a_lecart(data_dir, monkeypatch):
    fichier = data_dir / "user_settings.json"
    fichier.write_text('{"qualite": "720"}', encoding="utf-8")

    def _refuse(*a, **k):
        raise PermissionError("fichier verrouille")

    monkeypatch.setattr("builtins.open", _refuse)
    assert user_settings.load_settings() == user_settings.DEFAULT_SETTINGS
    monkeypatch.undo()

    # Un verrou passager n'est pas une corruption : le fichier reste en place.
    assert fichier.exists()
    assert not (data_dir / "user_settings.json.corrupt").exists()


def test_reglages_valides_inchanges(data_dir):
    fichier = data_dir / "user_settings.json"
    fichier.write_text('{"qualite": "480"}', encoding="utf-8")

    assert user_settings.load_settings()["qualite"] == "480"
    assert not (data_dir / "user_settings.json.corrupt").exists()


def test_les_copies_successives_ne_s_ecrasent_pas(tmp_path):
    for i in range(3):
        cible = tmp_path / "conf.json"
        cible.write_text(f"contenu {i}", encoding="utf-8")
        mettre_a_lecart(cible, "test")

    assert (tmp_path / "conf.json.corrupt").read_text(encoding="utf-8") == "contenu 0"
    assert (tmp_path / "conf.json.corrupt-1").read_text(encoding="utf-8") == "contenu 1"
    assert (tmp_path / "conf.json.corrupt-2").read_text(encoding="utf-8") == "contenu 2"


def test_le_nombre_de_copies_est_borne(tmp_path):
    for i in range(MAX_ECARTS + 3):
        cible = tmp_path / "conf.json"
        cible.write_text(f"c{i}", encoding="utf-8")
        mettre_a_lecart(cible, "test")

    # Au-dela du plafond on laisse le fichier en place plutot que de remplir le
    # dossier de donnees.
    assert (tmp_path / "conf.json").exists()
    assert not (tmp_path / f"conf.json.corrupt-{MAX_ECARTS + 1}").exists()
