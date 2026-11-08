"""Controle de sante de la librairie (engine/library/sante.py).

Mesure du 07/11/2026 chez l'utilisateur : 190 MP4 sur 1693 etaient des flux
MPEG-TS bruts, illisibles par le <video> de l'app, et 4 etaient tronques.
"""

import os
import struct
import subprocess
import time

import pytest

from engine.library import sante

_VIEUX = time.time() - 3 * 86400


def _mp4_valide() -> bytes:
    ftyp = struct.pack(">I4s", 16, b"ftyp") + b"isom" + b"\x00\x00\x02\x00"
    return ftyp + struct.pack(">I4s", 8, b"moov") + struct.pack(">I4s", 16, b"mdat") + b"\x00" * 8


def _mp4_tronque() -> bytes:
    ftyp = struct.pack(">I4s", 16, b"ftyp") + b"isom" + b"\x00\x00\x02\x00"
    return ftyp + struct.pack(">I4s", 10_000, b"mdat") + b"\x00" * 100


def _flux_ts() -> bytes:
    return (b"\x47" + b"\x00" * 187) * 4


def _poser(chemin, contenu: bytes, mtime: float = _VIEUX) -> str:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    os.utime(chemin, (mtime, mtime))
    return str(chemin)


@pytest.fixture
def librairie(tmp_path, monkeypatch):
    racine = tmp_path / "anime"
    racine.mkdir()
    monkeypatch.setattr("engine.library.scanner.dossiers_actifs", lambda: [racine])
    return racine


def _par_fichier(resultat: dict) -> dict:
    return {p["fichier"]: p for p in resultat["problemes"]}


def test_analyse_classe_chaque_defaut_et_ignore_le_sain(librairie):
    s = librairie / "Oeuvre" / "Saison 01"
    _poser(s / "E01.mp4", _mp4_valide())
    _poser(s / "E02.mp4", _flux_ts())
    _poser(s / "E03.mp4", _mp4_tronque())
    _poser(s / "E04.MUX.mp4", _mp4_valide())
    _poser(s / "E01.MUX.mp4", _mp4_valide())
    _poser(s / "E05.ts", _flux_ts())
    _poser(s / "E01.ts", _flux_ts())
    _poser(s / "E06.mp4.part", b"x")

    probs = _par_fichier(sante.analyser())

    assert "E01.mp4" not in probs
    assert (probs["E02.mp4"]["type"], probs["E02.mp4"]["action"]) == ("ts", "convertir")
    assert probs["E02.mp4"]["cible"] == probs["E02.mp4"]["chemin"]
    assert (probs["E03.mp4"]["type"], probs["E03.mp4"]["action"]) == ("tronque", "supprimer")
    assert probs["E04.MUX.mp4"]["action"] == "renommer"
    assert probs["E04.MUX.mp4"]["cible"].endswith("E04.mp4")
    assert probs["E01.MUX.mp4"]["type"] == "residu"  # doublon : E01.mp4 existe
    assert probs["E05.ts"]["action"] == "convertir" and probs["E05.ts"]["cible"].endswith("E05.mp4")
    assert probs["E01.ts"]["type"] == "residu"  # deja converti
    assert probs["E06.mp4.part"]["type"] == "residu"
    assert probs["E02.mp4"]["anime"] == "Oeuvre" and probs["E02.mp4"]["saison"] == "Saison 01"


def test_fichier_recent_ni_signale_ni_touche(librairie):
    # Moins d'une heure : peut appartenir a un telechargement en cours.
    chemin = _poser(librairie / "O" / "S" / "E.mp4.part", b"x", mtime=time.time())
    assert sante.analyser()["problemes"] == []
    assert sante.reparer_un(chemin) == (True, "Déjà sain")
    assert os.path.exists(chemin)


def test_seule_la_profondeur_de_la_librairie_est_parcourue(librairie):
    _poser(librairie / "egare.mp4.part", b"x")
    _poser(librairie / "O" / "S" / "sous" / "E.mp4.part", b"x")
    _poser(librairie / "_cache" / "S" / "E.mp4.part", b"x")
    assert sante.analyser()["problemes"] == []


def test_reparer_refuse_hors_librairie_et_rejuge(librairie, tmp_path):
    dehors = _poser(tmp_path / "ailleurs" / "x" / "E.mp4.part", b"x")
    assert sante.reparer_un(dehors) == (False, "Hors des dossiers de la librairie")
    assert os.path.exists(dehors)

    mux = _poser(librairie / "O" / "S" / "E.MUX.mp4", _mp4_valide())
    assert sante.reparer_un(mux) == (True, "Renommé")
    assert (librairie / "O" / "S" / "E.mp4").exists() and not os.path.exists(mux)

    residu = _poser(librairie / "O" / "S" / "E.ts", _flux_ts())
    assert sante.reparer_un(residu) == (True, "Supprimé")  # E.mp4 complet : doublon


def test_conversion_sans_ffmpeg_laisse_l_original(librairie, monkeypatch):
    monkeypatch.setattr("engine.download.methods.nm3u8dl._find_ffmpeg", lambda: None)
    chemin = _poser(librairie / "O" / "S" / "E.mp4", _flux_ts())
    assert sante.reparer_un(chemin) == (False, "ffmpeg introuvable")
    assert open(chemin, "rb").read() == _flux_ts()


def _ffmpeg_reel():
    from engine.download.methods.nm3u8dl import _find_ffmpeg
    return _find_ffmpeg()


@pytest.mark.skipif(not _ffmpeg_reel(), reason="ffmpeg absent")
def test_conversion_reelle_garde_la_date_et_ne_laisse_rien(librairie, tmp_path, monkeypatch):
    chemin = librairie / "O" / "S" / "E.mp4"
    chemin.parent.mkdir(parents=True)
    subprocess.run(
        [_ffmpeg_reel(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=duration=2:size=320x240:rate=25",
         "-f", "lavfi", "-i", "sine=duration=2", "-vf", "noise=alls=80:allf=t",
         "-c:v", "mpeg4", "-q:v", "2", "-c:a", "aac", "-f", "mpegts", str(chemin)],
        # Bruite pour un debit d'episode (6 Mo) : une mire nue se compresse a 30 Ko,
        # et l'enveloppe TS y depasse alors les 20 % toleres.
        check=True, timeout=60,
    )
    os.utime(chemin, (_VIEUX, _VIEUX))
    travaux = tmp_path / "temp"
    travaux.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(travaux))

    assert sante.classer(str(chemin))["action"] == "convertir"
    assert sante.reparer_un(str(chemin)) == (True, "Converti en MP4")

    from engine.download._engine_utils import mp4_complet
    assert mp4_complet(str(chemin))
    assert abs(os.path.getmtime(chemin) - _VIEUX) < 2
    assert sorted(p.name for p in chemin.parent.iterdir()) == ["E.mp4"]
    assert list(travaux.iterdir()) == []


@pytest.mark.skipif(not _ffmpeg_reel(), reason="ffmpeg absent")
def test_conversion_ratee_garde_l_original(librairie, tmp_path, monkeypatch):
    # Des paquets TS vides : ffmpeg n'y trouve aucun flux et echoue.
    chemin = _poser(librairie / "O" / "S" / "E.mp4", _flux_ts())
    travaux = tmp_path / "temp"
    travaux.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(travaux))

    ok, message = sante.reparer_un(chemin)

    assert not ok and message
    assert open(chemin, "rb").read() == _flux_ts()
    assert list(travaux.iterdir()) == []


def test_tache_de_fond_compte_et_signale_les_echecs(librairie, tmp_path, monkeypatch):
    monkeypatch.setattr(sante, "_etat", dict(sante._etat, en_cours=False))
    residu = _poser(librairie / "O" / "S" / "E.mp4.part", b"x")
    dehors = _poser(tmp_path / "x" / "y" / "z.mp4.part", b"x")

    assert sante.demarrer_reparation([residu, dehors, residu])["total"] == 2
    limite = time.time() + 10
    while sante.etat()["en_cours"] and time.time() < limite:
        time.sleep(0.02)

    e = sante.etat()
    assert (e["en_cours"], e["faits"], e["reussis"]) == (False, 2, 1)
    assert e["echecs"] == [{"chemin": dehors, "message": "Hors des dossiers de la librairie"}]
    assert not os.path.exists(residu)


def test_une_seule_reparation_a_la_fois(monkeypatch):
    monkeypatch.setattr(sante, "_etat", dict(sante._etat, en_cours=True))
    assert sante.demarrer_reparation(["x"]) == {"ok": False, "message": "Une réparation est déjà en cours"}
    assert sante.demarrer_reparation([]) == {"ok": False, "message": "Rien à réparer"}


def test_annuler_tue_la_conversion_en_cours(monkeypatch):
    tues = []

    class _Proc:
        def poll(self):
            return None

    monkeypatch.setattr(sante, "_proc", _Proc())
    monkeypatch.setattr(sante, "terminate_tree", tues.append)
    monkeypatch.setattr(sante, "_etat", dict(sante._etat, en_cours=True))
    sante.annuler_reparation()
    assert sante._annulation.is_set() and len(tues) == 1
    sante._annulation.clear()


def test_arret_de_l_app_sans_reparation_ne_laisse_pas_de_drapeau(monkeypatch):
    # L'arret de l'app appelle annuler_reparation a chaque fois : un drapeau leve
    # hors reparation faisait repondre « Annule » a la conversion suivante.
    monkeypatch.setattr(sante, "_etat", dict(sante._etat, en_cours=False))
    monkeypatch.setattr(sante, "_proc", None)
    sante.annuler_reparation()
    assert not sante._annulation.is_set()


def test_routes_branchees():
    from web.api.routes.anime.updates import router

    chemins = {r.path for r in router.routes}
    assert {"/sante-librairie", "/sante-librairie/etat", "/sante-librairie/reparer",
            "/sante-librairie/annuler"} <= chemins

