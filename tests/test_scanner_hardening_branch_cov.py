"""Regressions for library scanner hardening (2nd/3rd sweep).

- invalider_cache_dossiers reprend bien le dossier courant (cache 120 s).
- an empty dossiers result is not cached for the full TTL.
- same-named seasons across roots merge their episodes (no silent drop).
- symbol-only anime names don't collapse to one merged entry.
"""

import pytest

import engine.config.settings as cfg
from engine.library import scanner


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    scanner.invalider_cache_dossiers()
    scanner.invalider_cache_librairie()
    cfg.invalider_downloads_dir_cache()
    cfg.invalider_scans_dir_cache()
    yield
    scanner.invalider_cache_dossiers()
    scanner.invalider_cache_librairie()
    cfg.invalider_downloads_dir_cache()
    cfg.invalider_scans_dir_cache()


def _has(dossiers, path):
    target = str(path.resolve()).lower()
    return any(str(p).lower() == target for p in dossiers)


def test_dossiers_actifs_relit_apres_invalidation(monkeypatch, tmp_path):
    """Le cache dossiers tient 120 s : sans invalidation explicite, changer le
    dossier de telechargement laissait la librairie scanner l'ancien."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    empty = tmp_path / "none"
    courant = {"d": dir_a}

    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: courant["d"])
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: empty)

    assert _has(scanner.dossiers_actifs(), dir_a)

    courant["d"] = dir_b
    assert _has(scanner.dossiers_actifs(), dir_a), "cache encore chaud"

    scanner.invalider_cache_dossiers()
    got = scanner.dossiers_actifs()
    assert _has(got, dir_b)
    assert not _has(got, dir_a)


def test_empty_dossiers_not_cached(monkeypatch, tmp_path):
    missing = tmp_path / "gone"
    empty = tmp_path / "none"
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: missing)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: empty)

    assert scanner.dossiers_actifs() == []

    missing.mkdir()
    assert _has(scanner.dossiers_actifs(), missing)


def test_same_named_season_episodes_merged(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    sc = tmp_path / "sc"
    (dl / "Naruto" / "Saison 01").mkdir(parents=True)
    (dl / "Naruto" / "Saison 01" / "E1.mp4").write_bytes(b"x" * 10)
    (sc / "naruto" / "Saison 01").mkdir(parents=True)
    (sc / "naruto" / "Saison 01" / "Ch1.cbz").write_bytes(b"x" * 10)
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: sc)

    res = scanner.scan_librairie_sync()
    assert res["total"] == 1
    anime = res["animes"][0]
    assert len(anime["saisons"]) == 1
    noms = {e["nom"] for e in anime["saisons"][0]["episodes"]}
    assert noms == {"E1", "Ch1"}
    assert anime["total_eps"] == 2


def test_cle_fusion_symbol_only_names_not_collapsed():
    assert scanner._cle_fusion("!!!") == "!!!"
    assert scanner._cle_fusion("Naruto") == "naruto"
    assert scanner._cle_fusion("!!!") != scanner._cle_fusion("???")
