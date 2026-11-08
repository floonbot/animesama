"""Les fichiers « .MUX » laisses par N_m3u8DL-RE.

Comportement de N_m3u8DL-RE 0.6.0, mesure au banc local le 06/11/2026 avec la
commande exacte de l'app : il fusionne les segments en « nom.ts », remuxe en
« nom.MUX.mp4 », efface le .ts, puis renomme le MUX en « nom.mp4 ». Mais :

- si « nom.mp4 » existe deja, meme vide, il ne renomme pas et sort en code 0 :
  le resultat complet reste en « nom.MUX.mp4 » ;
- coupe pendant l'assemblage, il laisse le .ts et un « nom.MUX.mp4 » partiel.

Releve dans la librairie de l'utilisateur : huit episodes touches. Pour quatre,
yt-dlp passait ensuite pour avoir reussi en quelques secondes — sa recherche de
secours adoptait le .MUX de N_m3u8DL-RE — et laissait un « nom.mp4 » de 0 octet.
"""

import os
import struct
import threading

import pytest

import engine.config.logging_setup  # noqa: F401  (pose log.success, comme server.py au demarrage)
from engine.domain.exceptions import DownloadCancelled
from engine.download import _engine_utils as eu
from engine.download.methods import nm3u8dl, ytdlp_engine

NOM = "Serie - S01E010 VOSTFR"


def _boite(type_: bytes, charge: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(charge), type_) + charge


def _mp4_complet() -> bytes:
    return _boite(b"ftyp", b"isom" + b"\0" * 12) + _boite(b"mdat", b"v" * 4096) + _boite(b"moov", b"m" * 64)


def _mp4_coupe() -> bytes:
    # Ce que laisse un mux interrompu : ffmpeg n'a pas encore ecrit la taille
    # de mdat (0 = jusqu'a la fin du fichier), ni le moov qui vient apres.
    return _boite(b"ftyp", b"isom" + b"\0" * 12) + struct.pack(">I4s", 0, b"mdat") + b"v" * 4096


class _FauxProc:
    def __init__(self, lignes):
        self.returncode = 0
        self.pid = -1  # aucun vrai process ne doit etre vise par psutil
        self.stdout = iter(lignes)
        self.stderr = None

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        return None


class _FauxBinaire:
    """Ecrit les fichiers que le vrai binaire laisserait, puis rend sa sortie."""

    def __init__(self, fichiers, lignes):
        self._fichiers = fichiers
        self._lignes = lignes

    def __call__(self, cmd, *a, **k):
        dossier = cmd[cmd.index("--save-dir") + 1]
        nom = cmd[cmd.index("--save-name") + 1]
        for suffixe, contenu in self._fichiers.items():
            with open(os.path.join(dossier, nom + suffixe), "wb") as f:
                f.write(contenu)
        return _FauxProc(self._lignes)


@pytest.fixture
def binaire(monkeypatch):
    monkeypatch.setattr(nm3u8dl, "TAILLE_MIN_FICHIER", 1024)
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {})
    monkeypatch.setattr(nm3u8dl, "_monitor_tmp", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "_remux_fix", lambda chemin, cb: chemin)
    monkeypatch.setattr(nm3u8dl, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(nm3u8dl, "_terminate_tree", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(nm3u8dl, "unregister_proc", lambda *a, **k: None)

    def installer(fichiers, lignes):
        monkeypatch.setattr(nm3u8dl.subprocess, "Popen", _FauxBinaire(fichiers, lignes))

    return installer


def test_un_mux_complet_non_renomme_devient_l_episode(binaire, tmp_path):
    # Un « nom.mp4 » de 0 octet bloquait le renommage du binaire.
    (tmp_path / f"{NOM}.mp4").write_bytes(b"")
    binaire({".MUX.mp4": _mp4_complet()}, ["Muxing to x.MUX.mp4", "Cleaning files...", "Done"])

    res = nm3u8dl.nm3u8dl_download("http://h/x.m3u8", str(tmp_path), NOM)

    assert res == str(tmp_path / f"{NOM}.mp4")
    assert (tmp_path / f"{NOM}.mp4").read_bytes() == _mp4_complet()
    assert sorted(os.listdir(tmp_path)) == [f"{NOM}.mp4"]


def test_un_mux_coupe_n_est_pas_adopte(binaire, tmp_path):
    binaire({".MUX.mp4": _mp4_coupe()}, ["Muxing to x.MUX.mp4", "Done"])

    res = nm3u8dl.nm3u8dl_download("http://h/x.m3u8", str(tmp_path), NOM)

    assert res is None
    assert os.listdir(tmp_path) == []


def test_l_annulation_pendant_l_assemblage_ne_laisse_rien(binaire, tmp_path):
    # Tomb Raider King E012 : annule a l'assemblage, il restait un .ts complet
    # (pris ensuite pour l'episode termine) et un .MUX.mp4 de 408 Mo.
    binaire({".ts": b"t" * 8192, ".MUX.mp4": _mp4_coupe()}, ["Muxing to x.MUX.mp4"])

    with pytest.raises(DownloadCancelled):
        nm3u8dl.nm3u8dl_download("http://h/x.m3u8", str(tmp_path), NOM, cancelled=[True])

    assert os.listdir(tmp_path) == []


def test_mux_echoue_le_ts_reste_l_episode_et_le_mux_part(binaire, tmp_path):
    binaire({".ts": b"t" * 8192, ".MUX.mp4": b""}, ["Muxing to x.MUX.mp4", "ERROR: Mux failed"])

    res = nm3u8dl.nm3u8dl_download("http://h/x.m3u8", str(tmp_path), NOM)

    assert res == str(tmp_path / f"{NOM}.ts")
    assert sorted(os.listdir(tmp_path)) == [f"{NOM}.ts"]


def test_un_fichier_deja_la_n_est_pas_retire_sur_echec(binaire, tmp_path):
    # Ce que la tentative n'a pas ecrit ne la regarde pas.
    (tmp_path / f"{NOM}.ts").write_bytes(b"ancien" * 1000)
    binaire({}, ["Done"])

    nm3u8dl.nm3u8dl_download("http://h/x.m3u8", str(tmp_path), NOM)

    assert (tmp_path / f"{NOM}.ts").read_bytes() == b"ancien" * 1000


def test_yt_dlp_n_adopte_pas_le_mux_d_un_autre_moteur(tmp_path, monkeypatch):
    import engine.config.user_settings as user_settings

    monkeypatch.setattr(ytdlp_engine, "TAILLE_MIN_FICHIER", 1024)
    (tmp_path / f"{NOM}.MUX.mp4").write_bytes(_mp4_complet())

    def _popen(cmd, *a, **k):
        # yt-dlp sort en code 0 en ne laissant qu'un fichier vide. Avec -P, le
        # gabarit --output est relatif au dossier « home ».
        gabarit = cmd[cmd.index("--output") + 1].replace(".%(ext)s", ".mp4")
        homes = [cmd[i + 1][5:] for i, v in enumerate(cmd) if v == "-P" and cmd[i + 1].startswith("home:")]
        open(os.path.join(homes[0], gabarit) if homes else gabarit, "wb").close()
        return _FauxProc(["[download] 100.0%"])

    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", _popen)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)
    monkeypatch.setattr(user_settings, "load_settings", lambda: {"qualite": "auto"})

    assert ytdlp_engine.ytdlp_download("http://h/video.mp4", str(tmp_path), NOM) is None


@pytest.mark.parametrize(
    ("contenu", "attendu"),
    [
        (_mp4_complet(), True),
        (_mp4_coupe(), False),
        (_mp4_complet()[:-10], False),
        (b"", False),
        (_boite(b"ftyp", b"isom") + _boite(b"mdat", b"v" * 64), False),
    ],
    ids=["complet", "mux-coupe", "moov-tronque", "vide", "sans-moov"],
)
def test_mp4_complet(tmp_path, contenu, attendu):
    f = tmp_path / "v.mp4"
    f.write_bytes(contenu)

    assert eu.mp4_complet(str(f)) is attendu


def test_mp4_complet_lit_les_tailles_sur_64_bits(tmp_path):
    grande = struct.pack(">I4sQ", 1, b"mdat", 16 + 64) + b"v" * 64
    f = tmp_path / "v.mp4"
    f.write_bytes(_boite(b"ftyp", b"isom") + grande + _boite(b"moov", b"m"))

    assert eu.mp4_complet(str(f)) is True
