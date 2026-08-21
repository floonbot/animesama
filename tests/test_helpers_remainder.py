import os

import pytest

from engine.download import _helpers as h


@pytest.fixture(autouse=True)
def _snapshot_helper_globals():
    saved = {
        "TAILLE_MIN_FICHIER": h.TAILLE_MIN_FICHIER,
        "ESPACE_DISQUE_MIN_MB": h.ESPACE_DISQUE_MIN_MB,
    }
    yield
    for name, value in saved.items():
        setattr(h, name, value)


def test_normaliser_episodes_titre_default_anime():
    out = h.normaliser_episodes({"episodes": [{}]})
    assert out[0]["titre"] == "Anime"
    assert out[0]["saison"] == 1
    assert out[0]["episode"] == 0


def test_normaliser_episodes_titre_ref_from_nom_fallback():
    out = h.normaliser_episodes({"episodes": [{"nom": "FromNom"}, {}]})
    assert out[0]["titre"] == "FromNom"
    assert out[1]["titre"] == "FromNom"


def test_normaliser_episodes_existing_titre_preserved():
    out = h.normaliser_episodes({"episodes": [{"titre": "Ref"}, {"titre": "Own"}]})
    assert out[1]["titre"] == "Own"


def test_normaliser_episodes_empty_string_titre_replaced():
    out = h.normaliser_episodes({"episodes": [{"titre": "Ref"}, {"titre": ""}]})
    assert out[1]["titre"] == "Ref"


def test_normaliser_episodes_filters_non_dict_keeps_dicts():
    out = h.normaliser_episodes({"episodes": ["bad", 7, {"titre": "Keep"}, None]})
    assert len(out) == 1
    assert out[0]["titre"] == "Keep"


def test_normaliser_episodes_existing_saison_episode_kept():
    out = h.normaliser_episodes({"episodes": [{"titre": "T", "saison": 3, "episode": 9}]})
    assert out[0]["saison"] == 3
    assert out[0]["episode"] == 9


def test_normaliser_episodes_single_ep_non_dict_filtered():
    assert h.normaliser_episodes({"ep": "notadict"}) == []


def test_skip_existants_actif_true_when_setting_true(monkeypatch):
    import engine.config.user_settings as us

    monkeypatch.setattr(us, "load_settings", lambda: {"skip_existants": True})
    assert h.skip_existants_actif() is True


def test_skip_existants_actif_false_when_setting_false(monkeypatch):
    import engine.config.user_settings as us

    monkeypatch.setattr(us, "load_settings", lambda: {"skip_existants": False})
    assert h.skip_existants_actif() is False


def test_skip_existants_actif_true_when_key_missing(monkeypatch):
    import engine.config.user_settings as us

    monkeypatch.setattr(us, "load_settings", lambda: {})
    assert h.skip_existants_actif() is True


def test_skip_existants_actif_true_on_exception(monkeypatch):
    import engine.config.user_settings as us

    def _boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(us, "load_settings", _boom)
    assert h.skip_existants_actif() is True


def test_skip_existants_actif_true_when_truthy_string(monkeypatch):
    import engine.config.user_settings as us

    monkeypatch.setattr(us, "load_settings", lambda: {"skip_existants": "yes"})
    assert h.skip_existants_actif() is True


def test_espace_disque_suffisant_false_logs_warning(tmp_path, monkeypatch, caplog):
    class _Usage:
        free = 7 * 1024 * 1024

    monkeypatch.setattr(h.shutil, "disk_usage", lambda p: _Usage())
    with caplog.at_level("WARNING", logger="engine.download.helpers"):
        result = h.espace_disque_suffisant(str(tmp_path), minimum_mb=10)
    assert result is False
    assert any("low disk space" in r.message for r in caplog.records)
    assert any("7 MB" in r.getMessage() for r in caplog.records)


def test_espace_disque_suffisant_true_when_free_enough(tmp_path, monkeypatch):
    class _Usage:
        free = 800 * 1024 * 1024

    seen = {}

    def _fake(p):
        seen["path"] = p
        return _Usage()

    monkeypatch.setattr(h.shutil, "disk_usage", _fake)
    assert h.espace_disque_suffisant(str(tmp_path), minimum_mb=500) is True
    assert seen["path"] == str(tmp_path)


def test_espace_disque_suffisant_at_boundary_is_true(tmp_path, monkeypatch):
    class _Usage:
        free = 500 * 1024 * 1024

    monkeypatch.setattr(h.shutil, "disk_usage", lambda p: _Usage())
    assert h.espace_disque_suffisant(str(tmp_path), minimum_mb=500) is True


def test_espace_disque_suffisant_walks_up_to_existing_parent(tmp_path, monkeypatch):
    deep = tmp_path / "a" / "b" / "c"
    calls = {}

    class _Usage:
        free = 9000 * 1024 * 1024

    def _fake(p):
        calls["path"] = p
        return _Usage()

    monkeypatch.setattr(h.shutil, "disk_usage", _fake)
    assert h.espace_disque_suffisant(str(deep), minimum_mb=1) is True
    assert calls["path"] == str(tmp_path)


def test_espace_disque_suffisant_no_existing_dir_returns_true(monkeypatch):
    monkeypatch.setattr(h.os.path, "isdir", lambda p: False)

    def _should_not_run(p):
        raise AssertionError("disk_usage must not be called")

    monkeypatch.setattr(h.shutil, "disk_usage", _should_not_run)
    assert h.espace_disque_suffisant("relative-no-anchor", minimum_mb=1) is True


def test_espace_disque_suffisant_true_on_exception(tmp_path, monkeypatch):
    def _boom(p):
        raise OSError("denied")

    monkeypatch.setattr(h.shutil, "disk_usage", _boom)
    assert h.espace_disque_suffisant(str(tmp_path), minimum_mb=1) is True


def test_fichier_existe_matches_non_first_extension(tmp_path):
    from engine.config.settings import VIDEO_EXTENSIONS

    ext = VIDEO_EXTENSIONS[1]
    f = tmp_path / ("show" + ext)
    with open(f, "wb") as fh:
        fh.truncate(h.TAILLE_MIN_FICHIER + 100)
    assert h.fichier_existe(str(tmp_path), "show") == str(f)


def test_fichier_existe_at_min_size_is_none(tmp_path, monkeypatch):
    from engine.config.settings import VIDEO_EXTENSIONS

    monkeypatch.setattr(h, "TAILLE_MIN_FICHIER", 100)
    ext = VIDEO_EXTENSIONS[0]
    f = tmp_path / ("exact" + ext)
    with open(f, "wb") as fh:
        fh.truncate(100)
    assert h.fichier_existe(str(tmp_path), "exact") is None


def test_fichier_existe_just_above_min_size_returns_path(tmp_path, monkeypatch):
    from engine.config.settings import VIDEO_EXTENSIONS

    monkeypatch.setattr(h, "TAILLE_MIN_FICHIER", 100)
    ext = VIDEO_EXTENSIONS[0]
    f = tmp_path / ("over" + ext)
    with open(f, "wb") as fh:
        fh.truncate(101)
    assert h.fichier_existe(str(tmp_path), "over") == str(f)


def test_fichier_existe_no_matching_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "TAILLE_MIN_FICHIER", 1)
    (tmp_path / "ghost.txt").write_bytes(b"x" * 50)
    assert h.fichier_existe(str(tmp_path), "ghost") is None


def test_fichier_existe_getsize_oserror_skips_returns_none(tmp_path, monkeypatch):
    from engine.config.settings import VIDEO_EXTENSIONS

    ext = VIDEO_EXTENSIONS[0]
    target = os.path.join(str(tmp_path), "broken" + ext)
    (tmp_path / ("broken" + ext)).write_bytes(b"y" * 200)
    monkeypatch.setattr(h, "TAILLE_MIN_FICHIER", 1)

    real_getsize = h.os.path.getsize

    def _getsize(path):
        if path == target:
            raise OSError("stat failed")
        return real_getsize(path)

    monkeypatch.setattr(h.os.path, "getsize", _getsize)
    assert h.fichier_existe(str(tmp_path), "broken") is None


def test_fichier_existe_dir_exists_oserror_returns_none(monkeypatch):
    def _boom(path):
        raise OSError("exists failed")

    monkeypatch.setattr(h.os.path, "exists", _boom)
    assert h.fichier_existe("whatever", "name") is None
