from pathlib import Path

import pytest

import engine.config.settings as cfg
import engine.library.scanner as scanner
from engine.observability.metrics import metrics


@pytest.fixture(autouse=True)
def _reset_scanner_state():
    _max_orig = scanner.LIBRAIRIE_MAX_ANIMES
    _snap = metrics.snapshot()
    scanner.invalider_cache_dossiers()
    scanner.invalider_cache_librairie()
    cfg.invalider_downloads_dir_cache()
    cfg.invalider_scans_dir_cache()
    metrics.reset()
    yield
    scanner.LIBRAIRIE_MAX_ANIMES = _max_orig
    scanner.invalider_cache_dossiers()
    scanner.invalider_cache_librairie()
    cfg.invalider_downloads_dir_cache()
    cfg.invalider_scans_dir_cache()
    metrics.reset()
    for k, v in _snap.items():
        metrics.incr(k, v)


def _make_file(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _wire(monkeypatch, dl, sc):
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: sc)
    scanner.invalider_cache_dossiers()


class _BadResolveDir:
    def __init__(self, real: Path) -> None:
        self._real = real
        self.name = real.name

    def resolve(self):
        raise ValueError("resolve refused")

    def exists(self) -> bool:
        return self._real.exists()

    def __str__(self) -> str:
        return str(self._real)

    def __fspath__(self) -> str:
        return str(self._real)


class _FakeEntry:
    def __init__(self, fspath: Path, name: str) -> None:
        self._fspath = fspath
        self.name = name

    def __lt__(self, other) -> bool:
        return self.name < other.name

    def is_dir(self) -> bool:
        return True

    def __fspath__(self) -> str:
        return str(self._fspath)


class _FakeRoot:
    def __init__(self, entries) -> None:
        self._entries = entries

    def exists(self) -> bool:
        return True

    def iterdir(self):
        return list(self._entries)


def test_dossiers_actifs_resolve_failure_uses_raw_dir(monkeypatch, tmp_path):
    real = tmp_path / "dl_real"
    real.mkdir()
    bad = _BadResolveDir(real)
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: bad)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: tmp_path / "missing_scans")
    scanner.invalider_cache_dossiers()

    dossiers = scanner.dossiers_actifs()
    assert dossiers == [bad]


def test_dossiers_actifs_no_valid_dir_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: tmp_path / "ghost_dl")
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: tmp_path / "ghost_sc")
    scanner.invalider_cache_dossiers()

    assert scanner.dossiers_actifs() == []


def test_dossiers_actifs_cache_hit_returns_same_object(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    dl.mkdir()
    calls = {"n": 0}

    def _getter():
        calls["n"] += 1
        return dl

    monkeypatch.setattr(cfg, "get_downloads_dir", _getter)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: tmp_path / "missing_sc")
    scanner.invalider_cache_dossiers()

    first = scanner.dossiers_actifs()
    second = scanner.dossiers_actifs()
    assert first is second
    assert calls["n"] == 1


def test_dossiers_actifs_emits_cache_metrics(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: tmp_path / "missing_sc")
    scanner.invalider_cache_dossiers()

    scanner.dossiers_actifs()
    scanner.dossiers_actifs()
    snap = metrics.snapshot()
    assert snap.get("cache_miss_dossiers") == 1
    assert snap.get("cache_hit_dossiers") == 1


def test_est_dans_downloads_skips_base_with_resolve_error(monkeypatch, tmp_path):
    root = tmp_path / "downloads"
    inner = root / "A" / "Saison 01" / "E1.mp4"
    inner.parent.mkdir(parents=True)
    inner.write_bytes(b"x")
    monkeypatch.setattr(
        scanner, "dossiers_actifs", lambda: [_BadResolveDir(tmp_path / "x"), root]
    )
    assert scanner.est_dans_downloads(str(inner)) is True


def test_est_dans_downloads_only_bad_base_is_false(monkeypatch, tmp_path):
    root = tmp_path / "downloads"
    inner = root / "A" / "Saison 01" / "E1.mp4"
    inner.parent.mkdir(parents=True)
    inner.write_bytes(b"x")
    monkeypatch.setattr(
        scanner, "dossiers_actifs", lambda: [_BadResolveDir(tmp_path / "x")]
    )
    assert scanner.est_dans_downloads(str(inner)) is False


def test_scan_un_dossier_truncates_at_limit(monkeypatch, tmp_path):
    for nm in ("Aaa", "Bbb", "Ccc"):
        _make_file(tmp_path / nm / "Saison 01" / "E1.mp4")
    monkeypatch.setattr(scanner, "LIBRAIRIE_MAX_ANIMES", 2)

    animes, tronque = scanner._scan_un_dossier(tmp_path)
    assert tronque is True
    assert sorted(animes.keys()) == ["Aaa", "Bbb"]


def test_scan_un_dossier_skips_anime_when_scandir_raises():
    entry = _FakeEntry(Path("Z:/definitely/missing/anime_dir"), "Phantom")
    root = _FakeRoot([entry])

    animes, tronque = scanner._scan_un_dossier(root)
    assert animes == {}
    assert tronque is False


def test_scan_un_dossier_ignores_non_dir_season_entry(tmp_path):
    anime = tmp_path / "Show"
    (anime / "Saison 01").mkdir(parents=True)
    _make_file(anime / "Saison 01" / "E1.mp4")
    (anime / "loose.mp4").write_bytes(b"x" * 4)

    animes, tronque = scanner._scan_un_dossier(tmp_path)
    assert tronque is False
    saisons = animes["Show"]["saisons"]
    assert [s["nom"] for s in saisons] == ["Saison 01"]
    assert {e["nom"] for s in saisons for e in s["episodes"]} == {"E1"}
    assert animes["Show"]["total_eps"] == 1


def test_scan_un_dossier_skips_non_regular_video_name(tmp_path):
    saison = tmp_path / "Show" / "Saison 01"
    saison.mkdir(parents=True)
    _make_file(saison / "E1.mp4")
    (saison / "weird.mp4").mkdir()

    animes, _ = scanner._scan_un_dossier(tmp_path)
    eps = animes["Show"]["saisons"][0]["episodes"]
    assert {e["nom"] for e in eps} == {"E1"}
    assert animes["Show"]["total_eps"] == 1


def test_scan_un_dossier_counts_ts_as_video(tmp_path):
    saison = tmp_path / "Show" / "Saison 01"
    saison.mkdir(parents=True)
    _make_file(saison / "E1.ts", 7)

    animes, _ = scanner._scan_un_dossier(tmp_path)
    ep = animes["Show"]["saisons"][0]["episodes"][0]
    assert ep["nom"] == "E1"
    assert "scan" not in ep


def test_scan_un_dossier_sorts_seasons(tmp_path):
    anime = tmp_path / "Show"
    for sn in ("Saison 03", "Saison 01", "Saison 02"):
        s = anime / sn
        s.mkdir(parents=True)
        _make_file(s / "E1.mp4")

    animes, _ = scanner._scan_un_dossier(tmp_path)
    assert [s["nom"] for s in animes["Show"]["saisons"]] == [
        "Saison 01",
        "Saison 02",
        "Saison 03",
    ]


def test_scan_merges_overlapping_season_without_duplication(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    sc = tmp_path / "sc"
    _make_file(dl / "Dungeon Defense" / "Saison 01" / "E1.mp4", 1000)
    _make_file(sc / "dungeondefense" / "Saison 01" / "E1.cbz", 2000)
    _make_file(sc / "dungeondefense" / "Scan VF" / "C1.cbz", 500)
    _wire(monkeypatch, dl, sc)

    res = scanner.scan_librairie_sync()
    assert res["total"] == 1
    anime = res["animes"][0]
    assert anime["nom"] == "Dungeon Defense"
    assert [s["nom"] for s in anime["saisons"]] == ["Saison 01", "Scan VF"]
    assert anime["total_eps"] == 3


def test_scan_merge_aggregates_total_size(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    sc = tmp_path / "sc"
    half_gib = 512 * 1024 * 1024
    _make_file(dl / "Show" / "Saison 01" / "E1.mp4", half_gib)
    _make_file(sc / "show" / "Scan VF" / "C1.cbz", half_gib)
    _wire(monkeypatch, dl, sc)

    res = scanner.scan_librairie_sync()
    anime = res["animes"][0]
    assert "total_size_bytes" not in anime
    assert anime["total_size"] == round(2 * half_gib / 1024 / 1024 / 1024, 2)


def test_scan_truncation_propagates_to_result(monkeypatch, tmp_path):
    dl = tmp_path / "dl"
    for nm in ("Aaa", "Bbb", "Ccc"):
        _make_file(dl / nm / "Saison 01" / "E1.mp4")
    _wire(monkeypatch, dl, tmp_path / "missing_sc")
    monkeypatch.setattr(scanner, "LIBRAIRIE_MAX_ANIMES", 2)

    res = scanner.scan_librairie_sync()
    assert res["tronque"] is True
    assert res["total"] == 2


def test_scan_emits_librairie_cache_metrics():
    scanner.invalider_cache_librairie()
    assert scanner.librairie_cache_get() is None
    scanner.librairie_cache_set({"animes": [], "total": 0, "tronque": False})
    assert scanner.librairie_cache_get() is not None
    snap = metrics.snapshot()
    assert snap.get("cache_miss_librairie") == 1
    assert snap.get("cache_hit_librairie") == 1
