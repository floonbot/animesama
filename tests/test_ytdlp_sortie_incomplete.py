"""Regression : une video incomplete ne doit pas survivre a un telechargement coupe.

`--no-part` fait ecrire yt-dlp directement dans le fichier final. Coupe en route
— annulation utilisateur, abandon sur debit (C14), watchdog — il reste un .mp4
tronque, que `_nettoyer_fragments` epargne puisqu'il ressemble a une video finie.
Le lecteur suivant ne le refait alors pas : il le *reprend* par une requete Range.

Mesure sur deux sources distinctes servies en local, avant correctif : fichier de
2 000 000 o compose de 140 000 o du lecteur abandonne suivis de 1 860 000 o du
lecteur de secours, code retour 0 et taille finale exacte. Rien ne signalait la
corruption.
"""

import threading

import pytest

from engine.domain.exceptions import DownloadCancelled
from engine.download.methods import ytdlp_engine


class _Sortie:
    """Iterateur de lignes qui fait grossir le fichier, comme le vrai process."""

    def __init__(self, lignes, chemin, octets_par_ligne=0):
        self._lignes = list(lignes)
        self._i = 0
        self._chemin = chemin
        self._octets = octets_par_ligne

    def __iter__(self):
        return self

    def __next__(self):
        if self._i >= len(self._lignes):
            raise StopIteration
        ligne = self._lignes[self._i]
        self._i += 1
        if self._octets:
            with open(self._chemin, "ab") as f:
                f.write(b"A" * self._octets)
        return ligne

    def close(self):
        return None


class _Proc:
    def __init__(self, stdout, returncode=0):
        self.returncode = returncode
        self.pid = 4321
        self.stdout = stdout
        self.stderr = None

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        return None

    def terminate(self):
        return None


class _JetonCoupe:
    """Annule apres quelques lignes — un abandon sur debit en cours de route."""

    def __init__(self, apres=2):
        self._apres = apres
        self.lectures = 0

    def __bool__(self):
        return True

    def __getitem__(self, _i):
        self.lectures += 1
        return self.lectures > self._apres

    def is_cancelled(self):
        return self.lectures > self._apres


def _preparer(monkeypatch, proc):
    monkeypatch.setattr(ytdlp_engine.subprocess, "Popen", lambda *a, **k: proc)
    monkeypatch.setattr(ytdlp_engine, "_get_ytdlp_path", lambda: "yt-dlp")
    monkeypatch.setattr(ytdlp_engine, "_get_aria2c_path", lambda: None)
    monkeypatch.setattr(ytdlp_engine, "_terminate_tree", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "_spawn_proc_watchdog", lambda *a, **k: threading.Event())
    monkeypatch.setattr(ytdlp_engine, "register_proc", lambda *a, **k: None)
    monkeypatch.setattr(ytdlp_engine, "unregister_proc", lambda *a, **k: None)
    import engine.config.user_settings as user_settings
    monkeypatch.setattr(user_settings, "load_settings", lambda: {})


def test_commande_interdit_la_reprise():
    """Second verrou : meme un residu laisse par un autre moteur ne sera pas repris."""
    from engine.download.methods._ytdlp_parsing import construire_commande

    cmd = construire_commande("yt", "http://h/v", "/d", "n", {}, "auto")
    assert "--no-continue" in cmd


def test_nettoyer_fragments_epargne_la_video_partielle(tmp_path):
    """Le pourquoi du nouvel helper : l'ancien nettoyage ne voit pas le probleme."""
    partiel = tmp_path / "ep.mp4"
    partiel.write_bytes(b"A" * 140_000)

    assert ytdlp_engine._nettoyer_fragments(str(tmp_path), "ep") == 0
    assert partiel.exists()


def test_video_partielle_supprimee_quand_le_telechargement_est_coupe(tmp_path, monkeypatch):
    cible = tmp_path / "ep.mp4"
    proc = _Proc(_Sortie(
        ["[download]   1.0% of 200.00MiB at 190.00KiB/s ETA 17:00"] * 6,
        str(cible), octets_par_ligne=20_000,
    ))
    _preparer(monkeypatch, proc)

    with pytest.raises(DownloadCancelled):
        ytdlp_engine.ytdlp_download(
            "http://host.example/v", str(tmp_path), "ep", {}, _JetonCoupe(apres=2)
        )

    # Sans cela, le lecteur suivant reprendrait ces octets-la par une requete Range.
    assert not cible.exists()


def test_video_complete_conservee(tmp_path, monkeypatch):
    cible = tmp_path / "ep.mp4"
    proc = _Proc(_Sortie(["[download] 100% of 20.00MiB"], str(cible)))
    _preparer(monkeypatch, proc)
    monkeypatch.setattr(ytdlp_engine, "_trouver_fichier_final", lambda d, n: str(cible))
    cible.write_bytes(b"A" * 20_000_000)

    res = ytdlp_engine.ytdlp_download("http://host.example/v", str(tmp_path), "ep", {}, [False])

    assert res == str(cible)
    assert cible.exists()


def test_fichier_deja_complet_et_intact_survit_a_un_echec(tmp_path, monkeypatch):
    """Un echec ne doit pas emporter ce que cette tentative n'a pas ecrit."""
    ancien = tmp_path / "ep.mp4"
    ancien.write_bytes(b"A" * 20_000_000)
    proc = _Proc(_Sortie(["ERROR: unable to download"], str(ancien)), returncode=1)
    _preparer(monkeypatch, proc)

    res = ytdlp_engine.ytdlp_download("http://host.example/v", str(tmp_path), "ep", {}, [False])

    assert res is None
    assert ancien.exists()
    assert ancien.stat().st_size == 20_000_000


def test_video_partielle_supprimee_sur_code_retour_non_nul(tmp_path, monkeypatch):
    """Meme sortie anormale par le watchdog : le partiel ne doit pas rester."""
    cible = tmp_path / "ep.mp4"
    proc = _Proc(_Sortie(
        ["[download]   3.0% of 200.00MiB"] * 4, str(cible), octets_par_ligne=30_000,
    ), returncode=1)
    _preparer(monkeypatch, proc)

    res = ytdlp_engine.ytdlp_download("http://host.example/v", str(tmp_path), "ep", {}, [False])

    assert res is None
    assert not cible.exists()


def test_autre_episode_jamais_touche(tmp_path, monkeypatch):
    voisin = tmp_path / "autre episode.mp4"
    voisin.write_bytes(b"B" * 1024)
    cible = tmp_path / "ep.mp4"
    proc = _Proc(_Sortie(["[download]   2.0%"] * 3, str(cible), octets_par_ligne=10_000),
                 returncode=1)
    _preparer(monkeypatch, proc)

    ytdlp_engine.ytdlp_download("http://host.example/v", str(tmp_path), "ep", {}, [False])

    assert voisin.exists()
    assert not cible.exists()
