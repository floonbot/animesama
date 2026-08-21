import os

import pytest

import engine.config.settings as settings_mod
import engine.download.methods.nm3u8dl as nm3u8dl

URL = "https://exemple.test/master.m3u8"
NOM = "Titre S01E001 VOSTFR"


@pytest.fixture
def prepare(monkeypatch, tmp_path):
    exe = tmp_path / "N_m3u8DL-RE.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: str(exe))
    monkeypatch.setattr(nm3u8dl, "_find_ffmpeg", lambda: None)
    monkeypatch.setattr(
        nm3u8dl,
        "_get_user_settings",
        lambda: {"qualite": "auto", "thread_count": 16, "downloads_dir": ""},
    )
    return nm3u8dl._preparer_nm3u8dl


def _save_dir(cmd):
    return cmd[cmd.index("--save-dir") + 1]


def test_dossier_inchange_sous_sous_dossier_du_defaut(prepare, monkeypatch, tmp_path):
    defaut = tmp_path / "downloads"
    perso = defaut / "perso"
    perso.mkdir(parents=True)
    monkeypatch.setattr(settings_mod, "DOWNLOADS_DIR", defaut)
    monkeypatch.setattr(settings_mod, "get_downloads_dir", lambda: perso)

    dossier = str(perso / "Titre" / "Saison 01")
    res = prepare(URL, dossier, NOM, {}, None)

    assert res is not None
    assert res[0] == dossier
    assert _save_dir(res[2]) == dossier
    assert os.path.join("perso", "perso") not in _save_dir(res[2])


def test_dossier_inchange_dossier_par_defaut(prepare, monkeypatch, tmp_path):
    defaut = tmp_path / "downloads"
    defaut.mkdir()
    monkeypatch.setattr(settings_mod, "DOWNLOADS_DIR", defaut)
    monkeypatch.setattr(settings_mod, "get_downloads_dir", lambda: defaut)

    dossier = str(defaut / "Titre" / "Saison 01")
    res = prepare(URL, dossier, NOM, {}, None)

    assert res is not None
    assert res[0] == dossier
    assert _save_dir(res[2]) == dossier


def test_dossier_inchange_hors_arborescence(prepare, monkeypatch, tmp_path):
    defaut = tmp_path / "downloads"
    defaut.mkdir()
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    monkeypatch.setattr(settings_mod, "DOWNLOADS_DIR", defaut)
    monkeypatch.setattr(settings_mod, "get_downloads_dir", lambda: ailleurs)

    dossier = str(ailleurs / "Titre" / "Saison 01")
    res = prepare(URL, dossier, NOM, {}, None)

    assert res is not None
    assert res[0] == dossier
    assert _save_dir(res[2]) == dossier


def test_tmp_dir_sous_le_dossier_recu(prepare, monkeypatch, tmp_path):
    defaut = tmp_path / "downloads"
    perso = defaut / "perso"
    perso.mkdir(parents=True)
    monkeypatch.setattr(settings_mod, "DOWNLOADS_DIR", defaut)
    monkeypatch.setattr(settings_mod, "get_downloads_dir", lambda: perso)

    dossier = str(perso / "Titre" / "Saison 01")
    res = prepare(URL, dossier, NOM, {}, None)

    assert res is not None
    assert res[1] == os.path.join(dossier, "_tmp_" + NOM)
