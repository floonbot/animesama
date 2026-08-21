"""Cout du moniteur de progression de N_m3u8DL-RE.

Il tourne une fois par seconde pendant tout le telechargement et refaisait un
os.path.isfile + os.path.getsize par segment deja telecharge : le cout
croissait avec l'avancement, jusqu'a 90 ms par tick pour 1500 segments.
"""

import os


def _fabriquer_segments(tmp_path, n: int, taille: int = 2048):
    for i in range(n):
        (tmp_path / f"seg_{i:05d}.ts").write_bytes(b"x" * taille)
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    return tmp_path


def _etat(total_segs: int = 10) -> dict:
    import time

    return {
        "total_segs": total_segs,
        "start_time": time.time() - 5,
        "last_size": 0,
        "last_time": time.time() - 5,
        "speed_bps": 0.0,
        "phase": "downloading",
    }


def test_un_seul_parcours_du_dossier_par_tick(tmp_path, monkeypatch):
    from engine.download.methods import nm3u8dl

    _fabriquer_segments(tmp_path, 40)
    par_fichier = {"n": 0}
    parcours = {"n": 0}

    for module, nom in ((os, "stat"), (os, "listdir"), (os.path, "getsize"), (os.path, "isfile")):
        reel = getattr(module, nom)

        def compte(*a, _reel=reel, **k):
            par_fichier["n"] += 1
            return _reel(*a, **k)

        monkeypatch.setattr(module, nom, compte)

    scandir_reel = os.scandir

    def scandir_compte(*a, **k):
        parcours["n"] += 1
        return scandir_reel(*a, **k)

    monkeypatch.setattr(os, "scandir", scandir_compte)

    nm3u8dl._mesurer_progression_tmp(str(tmp_path), _etat(40), None)
    assert parcours["n"] == 1, f"{parcours['n']} parcours de dossier au lieu d'un"
    assert par_fichier["n"] == 0, (
        f"{par_fichier['n']} appels systeme par fichier pour 40 segments"
    )


def test_taille_et_compte_identiques_a_la_version_par_fichier(tmp_path):
    from engine.download.methods import nm3u8dl

    _fabriquer_segments(tmp_path, 25, taille=1024)
    (tmp_path / "part.m4s").write_bytes(b"y" * 500)
    (tmp_path / "final.mp4").write_bytes(b"z" * 300)

    state = _etat(30)
    state["last_time"] = 0.0
    lignes = []
    nm3u8dl._mesurer_progression_tmp(
        str(tmp_path), state, lambda pct, ligne: lignes.append((pct, ligne))
    )
    assert lignes, "aucune progression emise"
    pct, ligne = lignes[-1]
    assert "27/30 segments" in ligne
    assert state["last_size"] == 25 * 1024 + 500 + 300


def test_dossier_disparu_pendant_le_tick_ne_leve_pas(tmp_path):
    from engine.download.methods import nm3u8dl

    nm3u8dl._mesurer_progression_tmp(str(tmp_path / "absent"), _etat(5), None)


def test_sous_dossier_ignore(tmp_path):
    from engine.download.methods import nm3u8dl

    _fabriquer_segments(tmp_path, 3)
    (tmp_path / "sous.ts").mkdir()
    state = _etat(3)
    state["last_time"] = 0.0
    nm3u8dl._mesurer_progression_tmp(str(tmp_path), state, None)
    assert state["last_size"] == 3 * 2048


def test_aucune_emission_hors_phase_downloading(tmp_path):
    from engine.download.methods import nm3u8dl

    _fabriquer_segments(tmp_path, 3)
    state = _etat(3)
    state["phase"] = "muxing"
    lignes = []
    nm3u8dl._mesurer_progression_tmp(str(tmp_path), state, lambda p, l: lignes.append(l))
    assert lignes == []
