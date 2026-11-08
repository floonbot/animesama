"""Regression : la progression de N_m3u8DL-RE restait a « 0/71 segments ».

N_m3u8DL-RE 0.6.0 range ses segments sous « <tmp>/<nom>/<piste>/00.ts » (releve
le 07/11/2026 sur un banc HLS local, puis sur un vrai telechargement). Le
moniteur ne lisait que le premier niveau de --tmp-dir : 0 % jusqu'a
l'assemblage, et le temps restant de l'interface, qui se mesure sur
l'avancement, ne s'affichait jamais.
"""

import json

from engine.download.methods import nm3u8dl


def _etat(total_console=0):
    return {"total_segs": total_console, "start_time": 0.0, "last_size": 0,
            "last_time": 0.0, "speed_bps": 0.0, "phase": "downloading"}


def _arbre(tmp, pistes: dict[str, int], attendus: dict[str, int] | None = None):
    base = tmp / "Episode"
    for piste, n in pistes.items():
        d = base / piste
        d.mkdir(parents=True)
        for i in range(n):
            (d / f"{i:02d}.ts").write_bytes(b"x" * 100)
    if attendus is not None:
        (base / "meta_selected.json").write_text(
            json.dumps([{"Extension": "ts", "SegmentsCount": n} for n in attendus.values()]),
            encoding="utf-8-sig",
        )


def test_segments_ranges_deux_niveaux_plus_bas_sont_comptes(tmp_path):
    _arbre(tmp_path, {"0____": 25})
    lignes = []
    nm3u8dl._mesurer_progression_tmp(str(tmp_path), _etat(71), lambda p, l: lignes.append((p, l)))
    pct, ligne = lignes[-1]
    assert 35.0 < pct < 35.3
    assert "25/71 segments" in ligne


def test_total_lu_dans_meta_selected_quand_video_et_audio_sont_separes(tmp_path):
    # La console annonce « N Segments » piste par piste : seule la derniere
    # (l'audio, 40) restait, et 60 + 30 segments faits depassaient 100 %.
    _arbre(tmp_path, {"0____": 60, "1____": 30}, attendus={"video": 120, "audio": 40})
    etat = _etat(40)
    lignes = []
    nm3u8dl._mesurer_progression_tmp(str(tmp_path), etat, lambda p, l: lignes.append((p, l)))
    assert etat["segs_attendus"] == 160
    pct, ligne = lignes[-1]
    assert abs(pct - 90 / 160 * 100) < 0.1
    assert "90/160 segments" in ligne


def test_meta_en_cours_d_ecriture_relue_au_tick_suivant(tmp_path):
    _arbre(tmp_path, {"0____": 10})
    meta = tmp_path / "Episode" / "meta_selected.json"
    meta.write_text("[{\"SegmentsCount\": ", encoding="utf-8")
    etat = _etat(20)
    nm3u8dl._mesurer_progression_tmp(str(tmp_path), etat, None)
    assert not etat.get("segs_attendus")
    meta.write_text(json.dumps([{"SegmentsCount": 40}]), encoding="utf-8")
    nm3u8dl._mesurer_progression_tmp(str(tmp_path), etat, None)
    assert etat["segs_attendus"] == 40


def test_dossier_absent_ne_signale_rien(tmp_path):
    lignes = []
    nm3u8dl._mesurer_progression_tmp(str(tmp_path / "absent"), _etat(10), lambda p, l: lignes.append(p))
    assert lignes == []


def test_la_file_expose_l_index_de_l_episode_en_cours():
    # Une interface ouverte en cours de route ne voit pas episode_start : sans
    # cet index, elle se croyait au premier et dernier episode de l'anime.
    from engine.download.queue import _projeter_item

    projete = _projeter_item({"id": "a", "episodes": [{}, {}, {}], "index_episode": 1})
    assert projete["index_episode"] == 1 and projete["nb_episodes"] == 3


def test_le_worker_tient_l_index_a_jour_episode_par_episode(monkeypatch):
    import asyncio

    from engine.download import worker
    from tests.test_worker_remainder import FakeQueue

    item = {"episodes": [{"titre": "X"}, {"titre": "X"}, {"titre": "X"}]}
    vus = []

    async def _un(ep, i, total, titre, q):
        vus.append(item.get("index_episode"))
        return "succes"

    async def _sans_pause(_q):
        return None

    monkeypatch.setattr(worker, "_traiter_un_episode", _un)
    monkeypatch.setattr(worker, "_pause_anti_ban", _sans_pause)
    monkeypatch.setattr(worker, "_PREFETCH_ENABLED", False)
    asyncio.run(worker._traiter_episode(item, FakeQueue()))
    assert vus == [0, 1, 2]
