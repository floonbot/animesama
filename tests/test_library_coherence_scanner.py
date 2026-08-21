import asyncio

import pytest

import engine.config.settings as cfg
import engine.library.coherence as coherence
import engine.library.scanner as scanner


@pytest.fixture(autouse=True)
def _reset_scanner_caches():
    scanner.invalider_cache_dossiers()
    scanner.invalider_cache_librairie()
    cfg.invalider_downloads_dir_cache()
    cfg.invalider_scans_dir_cache()
    yield
    scanner.invalider_cache_dossiers()
    scanner.invalider_cache_librairie()
    cfg.invalider_downloads_dir_cache()
    cfg.invalider_scans_dir_cache()


def _make_video(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_num_saison_zero_padded():
    assert coherence._num_saison("Saison 01") == 1


def test_num_saison_spaced():
    assert coherence._num_saison("saison 2") == 2


def test_num_saison_non_saison():
    assert coherence._num_saison("bonus") is None


def test_num_saison_empty_and_none():
    assert coherence._num_saison("") is None
    assert coherence._num_saison(None) is None


def _anime_with_saison1(nom, n_eps, *, scan_eps=0):
    episodes = [{"nom": f"E{i}", "fichier": f"/x/E{i}.mp4"} for i in range(n_eps)]
    for i in range(scan_eps):
        episodes.append({"nom": f"C{i}", "fichier": f"/x/C{i}.cbz", "scan": True})
    return {"nom": nom, "saisons": [{"nom": "Saison 01", "episodes": episodes}]}


def _run_coherence(monkeypatch, animes, canon_map):
    monkeypatch.setattr(
        scanner, "scan_librairie_sync", lambda: {"animes": animes}
    )
    monkeypatch.setattr(
        coherence, "canon_saison1", lambda nom: canon_map.get(nom)
    )
    return asyncio.run(coherence.verifier_coherence_librairie())


def test_coherence_flags_excess_in_range(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 14)]
    canon = {"Naruto": {"matched": True, "finished": True, "episodes": 12}}
    res = _run_coherence(monkeypatch, animes, canon)
    assert res["total"] == 1
    assert res["verifies"] == 1
    assert res["matched"] == 1
    assert len(res["incoherents"]) == 1
    item = res["incoherents"][0]
    assert item == {"nom": "Naruto", "saison": 1, "local": 14, "canon": 12, "exces": 2}


def test_coherence_scan_episodes_excluded_from_local(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 14, scan_eps=5)]
    canon = {"Naruto": {"matched": True, "finished": True, "episodes": 12}}
    res = _run_coherence(monkeypatch, animes, canon)
    assert len(res["incoherents"]) == 1
    assert res["incoherents"][0]["local"] == 14
    assert res["incoherents"][0]["exces"] == 2


def test_coherence_excess_above_three_not_flagged(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 16)]
    canon = {"Naruto": {"matched": True, "finished": True, "episodes": 12}}
    res = _run_coherence(monkeypatch, animes, canon)
    assert res["matched"] == 1
    assert res["incoherents"] == []


def test_coherence_excess_zero_not_flagged(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 12)]
    canon = {"Naruto": {"matched": True, "finished": True, "episodes": 12}}
    res = _run_coherence(monkeypatch, animes, canon)
    assert res["incoherents"] == []


def test_coherence_excess_negative_not_flagged(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 10)]
    canon = {"Naruto": {"matched": True, "finished": True, "episodes": 12}}
    res = _run_coherence(monkeypatch, animes, canon)
    assert res["incoherents"] == []


def test_coherence_excess_exactly_three_flagged(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 15)]
    canon = {"Naruto": {"matched": True, "finished": True, "episodes": 12}}
    res = _run_coherence(monkeypatch, animes, canon)
    assert len(res["incoherents"]) == 1
    assert res["incoherents"][0]["exces"] == 3


def test_coherence_no_saison1_skipped(monkeypatch):
    anime = {"nom": "Bonus", "saisons": [{"nom": "bonus", "episodes": []}]}
    res = _run_coherence(monkeypatch, [anime], {})
    assert res["total"] == 1
    assert res["verifies"] == 0
    assert res["matched"] == 0
    assert res["incoherents"] == []


def test_coherence_canon_not_matched_skipped(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 14)]
    canon = {"Naruto": {"matched": False, "finished": True, "episodes": 12}}
    res = _run_coherence(monkeypatch, animes, canon)
    assert res["verifies"] == 1
    assert res["matched"] == 0
    assert res["incoherents"] == []


def test_coherence_canon_not_finished_skipped(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 14)]
    canon = {"Naruto": {"matched": True, "finished": False, "episodes": 12}}
    res = _run_coherence(monkeypatch, animes, canon)
    assert res["verifies"] == 1
    assert res["matched"] == 0
    assert res["incoherents"] == []


def test_coherence_canon_none_skipped(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 14)]
    res = _run_coherence(monkeypatch, animes, {})
    assert res["verifies"] == 1
    assert res["matched"] == 0
    assert res["incoherents"] == []


def test_coherence_canon_episodes_non_int_skipped(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 14)]
    canon = {"Naruto": {"matched": True, "finished": True, "episodes": None}}
    res = _run_coherence(monkeypatch, animes, canon)
    assert res["matched"] == 1
    assert res["incoherents"] == []


def test_coherence_canon_episodes_zero_skipped(monkeypatch):
    animes = [_anime_with_saison1("Naruto", 14)]
    canon = {"Naruto": {"matched": True, "finished": True, "episodes": 0}}
    res = _run_coherence(monkeypatch, animes, canon)
    assert res["matched"] == 1
    assert res["incoherents"] == []


def test_coherence_sort_order(monkeypatch):
    animes = [
        _anime_with_saison1("Bravo", 14),
        _anime_with_saison1("alpha", 14),
        _anime_with_saison1("Zeta", 15),
    ]
    canon = {
        "Bravo": {"matched": True, "finished": True, "episodes": 12},
        "alpha": {"matched": True, "finished": True, "episodes": 12},
        "Zeta": {"matched": True, "finished": True, "episodes": 12},
    }
    res = _run_coherence(monkeypatch, animes, canon)
    noms = [i["nom"] for i in res["incoherents"]]
    assert noms == ["Zeta", "alpha", "Bravo"]
    assert [i["exces"] for i in res["incoherents"]] == [3, 2, 2]


def test_coherence_empty_library(monkeypatch):
    res = _run_coherence(monkeypatch, [], {})
    assert res == {"incoherents": [], "total": 0, "verifies": 0, "matched": 0}


def test_est_dans_downloads_inside(monkeypatch, tmp_path):
    root = tmp_path / "downloads"
    inner = root / "Naruto" / "Saison 01" / "E1.mp4"
    inner.parent.mkdir(parents=True)
    inner.write_bytes(b"x")
    monkeypatch.setattr(scanner, "dossiers_actifs", lambda: [root])
    assert scanner.est_dans_downloads(str(inner)) is True


def test_est_dans_downloads_root_itself(monkeypatch, tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    monkeypatch.setattr(scanner, "dossiers_actifs", lambda: [root])
    assert scanner.est_dans_downloads(str(root)) is True


def test_est_dans_downloads_outside(monkeypatch, tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "secret.mp4"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"x")
    monkeypatch.setattr(scanner, "dossiers_actifs", lambda: [root])
    assert scanner.est_dans_downloads(str(outside)) is False


def test_est_dans_downloads_traversal(monkeypatch, tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    sibling = tmp_path / "etc_passwd"
    sibling.write_bytes(b"x")
    traversal = str(root / ".." / "etc_passwd")
    monkeypatch.setattr(scanner, "dossiers_actifs", lambda: [root])
    assert scanner.est_dans_downloads(traversal) is False


def test_est_dans_downloads_empty_arg(monkeypatch, tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    monkeypatch.setattr(scanner, "dossiers_actifs", lambda: [root])
    assert scanner.est_dans_downloads("") is False


def test_est_dans_downloads_non_str(monkeypatch, tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    monkeypatch.setattr(scanner, "dossiers_actifs", lambda: [root])
    assert scanner.est_dans_downloads(None) is False


def _wire_downloads_only(monkeypatch, dl):
    empty = dl.parent / "_no_scans"
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: empty)
    scanner.invalider_cache_dossiers()


def test_scan_builds_structure(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    _make_video(dl / "Naruto" / "Saison 01" / "S01E01.mp4", 1024 * 1024)
    _make_video(dl / "Naruto" / "Saison 01" / "S01E02.mkv", 2 * 1024 * 1024)
    _wire_downloads_only(monkeypatch, dl)

    res = scanner.scan_librairie_sync()
    assert res["total"] == 1
    assert res["tronque"] is False
    anime = res["animes"][0]
    assert anime["nom"] == "Naruto"
    assert anime["total_eps"] == 2
    assert len(anime["saisons"]) == 1
    saison = anime["saisons"][0]
    assert saison["nom"] == "Saison 01"
    noms = {e["nom"] for e in saison["episodes"]}
    assert noms == {"S01E01", "S01E02"}
    for e in saison["episodes"]:
        assert "scan" not in e


def test_scan_ignores_non_video_and_underscore_dir(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    _make_video(dl / "Naruto" / "Saison 01" / "S01E01.mp4")
    (dl / "Naruto" / "Saison 01" / "notes.txt").write_bytes(b"x")
    _make_video(dl / "_hidden" / "Saison 01" / "S01E01.mp4")
    _wire_downloads_only(monkeypatch, dl)

    res = scanner.scan_librairie_sync()
    assert res["total"] == 1
    anime = res["animes"][0]
    assert anime["nom"] == "Naruto"
    assert anime["total_eps"] == 1
    assert {e["nom"] for e in anime["saisons"][0]["episodes"]} == {"S01E01"}


def test_scan_marks_cbz_as_scan(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    _make_video(dl / "Berserk" / "Scan VF" / "Chapitre 1.cbz")
    _wire_downloads_only(monkeypatch, dl)

    res = scanner.scan_librairie_sync()
    ep = res["animes"][0]["saisons"][0]["episodes"][0]
    assert ep["scan"] is True
    assert ep["nom"] == "Chapitre 1"


def test_scan_skips_dir_without_episodes(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    (dl / "EmptyShow" / "Saison 01").mkdir(parents=True)
    _wire_downloads_only(monkeypatch, dl)

    res = scanner.scan_librairie_sync()
    assert res["total"] == 0
    assert res["animes"] == []


def test_scan_missing_root_returns_empty(monkeypatch, tmp_path):
    dl = tmp_path / "does_not_exist"
    empty = tmp_path / "_no_scans"
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: empty)
    scanner.invalider_cache_dossiers()

    res = scanner.scan_librairie_sync()
    assert res == {"animes": [], "total": 0, "tronque": False}


def test_scan_merges_downloads_and_scans(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    sc = tmp_path / "sc"
    _make_video(dl / "Dungeon Defense" / "Saison 01" / "S01E01.mp4")
    _make_video(sc / "dungeondefense" / "Scan VF" / "Chapitre 1.cbz")
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: sc)
    scanner.invalider_cache_dossiers()

    res = scanner.scan_librairie_sync()
    assert res["total"] == 1
    anime = res["animes"][0]
    saison_noms = {s["nom"] for s in anime["saisons"]}
    assert saison_noms == {"Saison 01", "Scan VF"}
    assert anime["total_eps"] == 2


def test_scan_total_size_gib(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    _make_video(dl / "Big" / "Saison 01" / "S01E01.mp4", 1024 * 1024)
    _wire_downloads_only(monkeypatch, dl)

    res = scanner.scan_librairie_sync()
    anime = res["animes"][0]
    assert "total_size_bytes" not in anime
    assert anime["total_size"] == round(1024 * 1024 / 1024 / 1024 / 1024, 2)
    ep = anime["saisons"][0]["episodes"][0]
    assert ep["taille"] == 1.0


def test_scan_un_dossier_directly(tmp_path):
    saison = tmp_path / "Mon Manga" / "Scan VF"
    saison.mkdir(parents=True)
    (saison / "Chapitre 1.cbz").write_bytes(b"x" * 5)
    animes, tronque = scanner._scan_un_dossier(tmp_path)
    assert tronque is False
    assert "Mon Manga" in animes
    eps = animes["Mon Manga"]["saisons"][0]["episodes"]
    assert eps[0]["scan"] is True
    assert eps[0]["nom"] == "Chapitre 1"


def test_scan_un_dossier_missing_root():
    animes, tronque = scanner._scan_un_dossier(scanner.Path("Z:/definitely/missing/path"))
    assert animes == {}
    assert tronque is False


def test_librairie_cache_get_set_invalidate():
    assert scanner.librairie_cache_get() is None
    payload = {"animes": [], "total": 0, "tronque": False}
    scanner.librairie_cache_set(payload)
    assert scanner.librairie_cache_get() == payload
    scanner.invalider_cache_librairie()
    assert scanner.librairie_cache_get() is None


def test_librairie_cache_distinguishes_empty_from_miss():
    scanner.librairie_cache_set({"animes": []})
    got = scanner.librairie_cache_get()
    assert got == {"animes": []}


def test_invalider_cache_dossiers_clears(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    empty = tmp_path / "_no_scans"
    dl.mkdir()
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: empty)
    scanner.invalider_cache_dossiers()
    first = scanner.dossiers_actifs()
    assert any(str(p).lower() == str(dl.resolve()).lower() for p in first)

    dl2 = tmp_path / "dl2"
    dl2.mkdir()
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl2)
    cached = scanner.dossiers_actifs()
    assert cached == first
    scanner.invalider_cache_dossiers()
    after = scanner.dossiers_actifs()
    assert any(str(p).lower() == str(dl2.resolve()).lower() for p in after)


def test_dossiers_actifs_dedupes_same_dir(monkeypatch, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: shared)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: shared)
    scanner.invalider_cache_dossiers()
    dossiers = scanner.dossiers_actifs()
    assert len(dossiers) == 1
