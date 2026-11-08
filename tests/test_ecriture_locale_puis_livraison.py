"""Les moteurs ecrivent en local, puis livrent dans le dossier de telechargement.

Mesure le 06/11/2026 sur le NAS de l'utilisateur (partage SMB) :
ffmpeg `-movflags +faststart` y echoue en fin de course — « Error writing trailer:
Invalid argument » —, et la meme commande vers un disque local reussit. Deux
moteurs ecrivaient directement sur le partage :

- le moteur ffmpeg (dernier recours) : 10 echecs au journal, 4,3 Go jetes apres
  un telechargement complet ;
- yt-dlp, dont la correction des flux HLS ajoute elle-meme +faststart : 21
  « Postprocessing: Conversion failed! ».

Le remux de N_m3u8DL-RE (`_remux_fix`) passait deja par un dossier local : c'est
lui qui marchait. Les faux binaires ci-dessous reproduisent le partage : toute
ecriture faststart directement dans le dossier final echoue.
"""

import os
import shutil
import tempfile
import threading

import pytest

import engine.config.logging_setup  # noqa: F401  (pose log.success, comme server.py)
from engine.download import _engine_utils as eu
from engine.download.methods import ffmpeg_engine, ytdlp_engine

NOM = "Serie - S01E005 VOSTFR"
VIDEO = b"\x00\x00\x00\x18ftypisom" + b"v" * 8192


class _FauxProc:
    def __init__(self, code, stderr_lignes=(), stdout_lignes=()):
        self.returncode = code
        self.pid = -1  # aucun vrai process ne doit etre vise par psutil
        self.stdout = iter(list(stdout_lignes))
        self.stderr = iter(list(stderr_lignes))

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        return None


def _sous(chemin: str, dossier) -> bool:
    return os.path.abspath(chemin).startswith(os.path.abspath(str(dossier)))


@pytest.fixture
def temp_isole(tmp_path, monkeypatch):
    base = tmp_path / "temp-local"
    base.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(base))
    return base


@pytest.fixture
def nas(tmp_path):
    d = tmp_path / "nas" / "Serie" / "Saison 01"
    d.mkdir(parents=True)
    return d


def _neutraliser(monkeypatch, module):
    monkeypatch.setattr(module, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(module, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(module, "unregister_proc", lambda *a, **k: None)


def test_ffmpeg_ecrit_en_local_puis_livre_sur_le_partage(nas, temp_isole, monkeypatch):
    def _ffmpeg(cmd, *a, **k):
        sortie = cmd[-1]
        with open(sortie, "wb") as f:
            f.write(VIDEO)
        if _sous(sortie, nas) and "+faststart" in cmd:
            return _FauxProc(4294967274, ["Error writing trailer: Invalid argument"])
        return _FauxProc(0)

    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", _ffmpeg)
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg_engine, "_estimer_duree_hls", lambda *a, **k: 0.0)
    monkeypatch.setattr(ffmpeg_engine, "TAILLE_MIN_FICHIER", 1024)
    _neutraliser(monkeypatch, ffmpeg_engine)

    res = ffmpeg_engine.ffmpeg_download("http://h/x.m3u8", str(nas), NOM)

    assert res == str(nas / f"{NOM}.mp4")
    assert (nas / f"{NOM}.mp4").read_bytes() == VIDEO
    assert os.listdir(nas) == [f"{NOM}.mp4"]
    assert os.listdir(temp_isole) == []


def _cible_ytdlp(cmd: list[str]) -> tuple[str, bool]:
    """Ou yt-dlp ecrirait, et s'il passe par un dossier de travail (-P temp:)."""
    gabarit = cmd[cmd.index("--output") + 1]
    chemins = {cmd[i + 1].split(":", 1)[0]: cmd[i + 1].split(":", 1)[1]
               for i, v in enumerate(cmd) if v == "-P"}
    final = os.path.join(chemins["home"], gabarit) if "home" in chemins else gabarit
    return final.replace(".%(ext)s", ".mp4"), "temp" in chemins


def test_yt_dlp_corrige_le_hls_en_local_puis_livre_sur_le_partage(nas, temp_isole, monkeypatch):
    import engine.config.user_settings as user_settings

    def _ytdlp(cmd, *a, **k):
        final, via_travail = _cible_ytdlp(cmd)
        if not via_travail and _sous(final, nas):
            # La correction HLS (faststart) echoue sur le partage : il reste
            # l'entree et un .temp.mp4, code 1.
            with open(final, "wb") as f:
                f.write(VIDEO)
            with open(final.replace(".mp4", ".temp.mp4"), "wb") as f:
                f.write(b"partiel")
            return _FauxProc(1, stdout_lignes=["ERROR: Postprocessing: Conversion failed!"])
        with open(final, "wb") as f:
            f.write(VIDEO)
        return _FauxProc(0, stdout_lignes=["[download] 100.0%"])

    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", _ytdlp)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 1024)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    _neutraliser(monkeypatch, ytdlp_engine)

    res = ytdlp_engine.ytdlp_download("http://h/x.m3u8", str(nas), NOM)

    assert res == str(nas / f"{NOM}.mp4")
    assert os.listdir(nas) == [f"{NOM}.mp4"]
    assert os.listdir(temp_isole) == []


def test_livrer_remplace_la_destination_sans_jamais_l_exposer_partielle(tmp_path, monkeypatch):
    source = tmp_path / "local" / "v.mp4"
    source.parent.mkdir()
    source.write_bytes(VIDEO)
    dest = tmp_path / "nas" / f"{NOM}.mp4"
    dest.parent.mkdir()
    dest.write_bytes(b"clip de 5 s")

    vrai_replace = os.replace
    appels = []

    def _replace(a, b):
        appels.append((a, b))
        if len(appels) == 1:  # le partage est un autre volume : pas de renommage direct
            raise OSError(17, "autre volume")
        return vrai_replace(a, b)

    monkeypatch.setattr(eu.os, "replace", _replace)

    eu.livrer(str(source), str(dest))

    assert dest.read_bytes() == VIDEO
    assert not source.exists()
    assert os.listdir(dest.parent) == [dest.name]


def test_livrer_une_copie_interrompue_ne_laisse_rien_d_adoptable(tmp_path, monkeypatch):
    source = tmp_path / "v.mp4"
    source.write_bytes(VIDEO)
    dest = tmp_path / "nas" / f"{NOM}.mp4"
    dest.parent.mkdir()

    monkeypatch.setattr(eu.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError(17, "autre volume")))

    def _copie_coupee(a, b):
        with open(b, "wb") as f:
            f.write(VIDEO[:100])
        raise OSError(5, "reseau coupe")

    monkeypatch.setattr(eu.shutil, "copyfile", _copie_coupee)

    with pytest.raises(OSError):
        eu.livrer(str(source), str(dest))

    assert os.listdir(dest.parent) == []
    assert source.exists()


@pytest.mark.parametrize("moteur", [ffmpeg_engine, ytdlp_engine], ids=["ffmpeg", "yt-dlp"])
def test_un_echec_juste_apres_la_creation_ne_laisse_pas_le_dossier_de_travail(
    moteur, nas, temp_isole, monkeypatch
):
    # Il etait cree avant le try : construire la commande en echec le laissait.
    import engine.config.user_settings as user_settings

    def _echec(*a, **k):
        raise ValueError("commande impossible")

    monkeypatch.setattr(moteur, "_construire_commande", _echec)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})
    monkeypatch.setattr(ffmpeg_engine, "_get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    _neutraliser(monkeypatch, moteur)
    telecharger = moteur.ffmpeg_download if moteur is ffmpeg_engine else moteur.ytdlp_download

    assert telecharger("http://h/x.m3u8", str(nas), NOM) is None
    assert os.listdir(temp_isole) == []


def test_le_dossier_de_travail_d_un_run_tue_est_purge(temp_isole):
    vieux = temp_isole / "animesama_travail_ancien"
    vieux.mkdir()
    (vieux / "v.mp4").write_bytes(b"x")
    ancien = os.path.getmtime(vieux) - 2 * 86400
    os.utime(vieux, (ancien, ancien))

    d = eu.creer_dossier_de_travail()
    try:
        assert not vieux.exists()
        assert os.path.isdir(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
