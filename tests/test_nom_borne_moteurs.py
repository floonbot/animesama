"""Regression : sous Windows, `borner_nom_fichier` raccourcit le nom que les
moteurs passent au binaire, mais nm3u8dl et yt-dlp cherchaient ensuite le fichier
produit sous le nom *complet*. Sur un titre long, un telechargement reussi etait
donc compte comme un echec : la cascade repartait sur le moteur suivant (jusqu'a
trois telechargements du meme episode), les residus n'etaient jamais nettoyes et
le dossier `_tmp_` etait conserve « pour reprise » alors que le fichier existait.
"""

import os
import threading

import pytest

from engine.download import _engine_utils as eu
from engine.download.methods import ffmpeg_engine, nm3u8dl, ytdlp_engine

TITRE_LONG = "Un Titre D Anime Vraiment Tres Long Qui Sature Le Chemin " * 4
NOM_LONG = f"{TITRE_LONG[:200]} - S01E001 VOSTFR"


@pytest.fixture
def sous_windows(monkeypatch):
    monkeypatch.setattr(eu.os, "name", "nt")


@pytest.fixture
def petits_seuils(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "TAILLE_MIN_FICHIER", 8)
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 8)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 8)


def _dossier_profond(tmp_path):
    d = tmp_path / "downloads" / "Un Titre D Anime Assez Long" / "Saison 01"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


class _FauxProc:
    def __init__(self, lignes):
        self.returncode = 0
        self.pid = 4321
        self.stdout = iter(lignes)
        self.stderr = None

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        return None

    def terminate(self):
        return None


class _PopenEcrivant:
    """Le binaire ecrit exactement le fichier que la commande lui demande."""

    def __init__(self, cible, lignes=()):
        self._cible = cible
        self._lignes = list(lignes)
        self.cmd: list[str] = []
        self.ecrit = ""

    def __call__(self, cmd, *a, **k):
        self.cmd = list(cmd)
        self.ecrit = self._cible(self.cmd)
        with open(self.ecrit, "wb") as f:
            f.write(b"x" * 4096)
        return _FauxProc(self._lignes)


def _cible_nm3u8dl(cmd):
    dossier = cmd[cmd.index("--save-dir") + 1]
    nom = cmd[cmd.index("--save-name") + 1]
    return os.path.join(dossier, nom + ".mp4")


def _cible_ytdlp(cmd):
    return cmd[cmd.index("--output") + 1].replace(".%(ext)s", ".mp4")


def _ecriture_directe():
    raise OSError("ecriture directe")


def _neutraliser(monkeypatch, module):
    monkeypatch.setattr(module, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(module, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(module, "unregister_proc", lambda *a, **k: None)
    # Ces tests visent l'analyse de la sortie des moteurs : ecriture directe.
    # Le passage par un dossier local : test_ecriture_locale_puis_livraison.py.
    if hasattr(module, "creer_dossier_de_travail"):
        monkeypatch.setattr(module, "creer_dossier_de_travail", _ecriture_directe)


def test_nm3u8dl_retrouve_le_fichier_ecrit_sous_le_nom_borne(
    sous_windows, petits_seuils, tmp_path, monkeypatch
):
    dossier = _dossier_profond(tmp_path)
    factory = _PopenEcrivant(_cible_nm3u8dl, ["Total 1 Segments found", "Done"])
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", factory)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)
    _neutraliser(monkeypatch, nm3u8dl)

    res = nm3u8dl.nm3u8dl_download("http://h/x.m3u8", dossier, NOM_LONG)

    assert factory.ecrit != os.path.join(dossier, NOM_LONG + ".mp4")
    assert res == factory.ecrit


def test_ytdlp_retrouve_le_fichier_ecrit_sous_le_nom_borne(
    sous_windows, petits_seuils, tmp_path, monkeypatch
):
    import engine.config.user_settings as user_settings

    dossier = _dossier_profond(tmp_path)
    factory = _PopenEcrivant(_cible_ytdlp, ["[download] 100.0%"])
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", factory)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    _neutraliser(monkeypatch, ytdlp_engine)

    res = ytdlp_engine.ytdlp_download("http://h/video", dossier, NOM_LONG)

    assert factory.ecrit != os.path.join(dossier, NOM_LONG + ".mp4")
    assert res == factory.ecrit


def test_ffmpeg_retrouve_le_fichier_ecrit_sous_le_nom_borne(
    sous_windows, petits_seuils, tmp_path, monkeypatch
):
    dossier = _dossier_profond(tmp_path)

    def _cible(cmd):
        return cmd[-1]

    factory = _PopenEcrivant(_cible)
    factory_proc = factory

    def _popen(cmd, *a, **k):
        proc = factory_proc(cmd, *a, **k)
        proc.stderr = iter(["frame=1"])
        return proc

    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", _popen)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda u, h: 0.0)
    _neutraliser(monkeypatch, ffmpeg_engine)

    res = ffmpeg_engine.ffmpeg_download("http://h/x.m3u8", dossier, NOM_LONG)

    assert factory.ecrit != os.path.join(dossier, NOM_LONG + ".mp4")
    assert res == factory.ecrit


def test_nm3u8dl_ne_conserve_pas_le_tmp_quand_le_fichier_existe(
    sous_windows, petits_seuils, tmp_path, monkeypatch
):
    dossier = _dossier_profond(tmp_path)
    nom_borne = eu.borner_nom_fichier(dossier, NOM_LONG, ".mp4", silencieux=True)
    tmp_dir = os.path.join(dossier, "_tmp_" + nom_borne)

    def _cible(cmd):
        os.makedirs(cmd[cmd.index("--tmp-dir") + 1], exist_ok=True)
        return _cible_nm3u8dl(cmd)

    factory = _PopenEcrivant(_cible, ["Done"])
    monkeypatch.setattr(nm3u8dl.subprocess, "Popen", factory)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)
    _neutraliser(monkeypatch, nm3u8dl)

    nm3u8dl.nm3u8dl_download("http://h/x.m3u8", dossier, NOM_LONG)

    assert not os.path.isdir(tmp_dir)
