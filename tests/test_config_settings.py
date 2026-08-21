import json
from pathlib import Path

import pytest

import engine.config.settings as settings


@pytest.fixture(autouse=True)
def _restore_globals():
    saved_data_dir = settings.DATA_DIR
    dl = settings._downloads_dir
    sc = settings._scans_dir
    saved = {
        "dl_val": dl._val,
        "dl_ts": dl._ts,
        "dl_default": dl._default,
        "sc_val": sc._val,
        "sc_ts": sc._ts,
        "sc_default": sc._default,
    }
    dl._val = None
    dl._ts = 0.0
    sc._val = None
    sc._ts = 0.0
    yield
    settings.DATA_DIR = saved_data_dir
    dl._val = saved["dl_val"]
    dl._ts = saved["dl_ts"]
    dl._default = saved["dl_default"]
    sc._val = saved["sc_val"]
    sc._ts = saved["sc_ts"]
    sc._default = saved["sc_default"]


def _write_user_settings(data_dir: Path, payload) -> Path:
    f = data_dir / "user_settings.json"
    if isinstance(payload, str):
        f.write_text(payload, encoding="utf-8")
    else:
        f.write_text(json.dumps(payload), encoding="utf-8")
    return f


def test_env_int_default_when_unset(monkeypatch):
    monkeypatch.delenv("MY_PORT", raising=False)
    assert settings._env_int("MY_PORT", 7843) == 7843


def test_env_int_parses_valid(monkeypatch):
    monkeypatch.setenv("MY_PORT", "8080")
    assert settings._env_int("MY_PORT", 7843) == 8080


def test_env_int_non_numeric_falls_back(monkeypatch):
    monkeypatch.setenv("MY_PORT", "abc")
    assert settings._env_int("MY_PORT", 7843) == 7843


def test_env_int_out_of_range_falls_back(monkeypatch):
    monkeypatch.setenv("MY_PORT", "70000")
    assert settings._env_int("MY_PORT", 7843, mini=1, maxi=65535) == 7843


def test_env_int_boundaries_inclusive(monkeypatch):
    monkeypatch.setenv("MY_VAL", "5")
    assert settings._env_int("MY_VAL", 99, mini=5, maxi=10) == 5
    monkeypatch.setenv("MY_VAL", "10")
    assert settings._env_int("MY_VAL", 99, mini=5, maxi=10) == 10


def test_host_is_hardcoded_loopback():
    assert settings.HOST == "127.0.0.1"


def test_safe_mkdir_creates_directory(tmp_path):
    target = tmp_path / "downloads" / "nested"
    out = settings._safe_mkdir(target, "DOWNLOADS_DIR")
    assert out == target
    assert target.is_dir()


def test_safe_mkdir_fallback_on_oserror(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ROOT_DIR", tmp_path)

    class _Boom:
        def mkdir(self, *a, **k):
            raise OSError("denied")

        def __str__(self):
            return "<boom>"

    out = settings._safe_mkdir(_Boom(), "DOWNLOADS_DIR")
    assert out == tmp_path / "downloads"
    assert (tmp_path / "downloads").is_dir()


def test_get_downloads_dir_default_when_no_user_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    default = tmp_path / "dl_default"
    settings._downloads_dir._default = default
    assert settings.get_downloads_dir() == default


def test_get_downloads_dir_override_from_user_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    custom = tmp_path / "custom_dl"
    custom.mkdir()
    _write_user_settings(tmp_path, {"downloads_dir": str(custom)})
    settings._downloads_dir._default = tmp_path / "dl_default"
    assert settings.get_downloads_dir() == custom


def test_get_downloads_dir_override_recreated_when_path_missing(tmp_path, monkeypatch):
    # Basculer en silence sur le dossier par defaut faisait atterrir les fichiers
    # ailleurs : on recree le dossier configure tant que c'est possible.
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    settings._downloads_dir._default = tmp_path / "dl_default"
    fantome = tmp_path / "ghost"
    _write_user_settings(tmp_path, {"downloads_dir": str(fantome)})
    assert settings.get_downloads_dir() == fantome
    assert fantome.is_dir()


def test_get_downloads_dir_override_ignored_when_not_a_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    default = tmp_path / "dl_default"
    settings._downloads_dir._default = default
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    _write_user_settings(tmp_path, {"downloads_dir": str(afile)})
    assert settings.get_downloads_dir() == default


def test_get_downloads_dir_blank_override_uses_default(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    default = tmp_path / "dl_default"
    settings._downloads_dir._default = default
    _write_user_settings(tmp_path, {"downloads_dir": "   "})
    assert settings.get_downloads_dir() == default


def test_get_scans_dir_override_from_user_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    custom = tmp_path / "custom_scans"
    custom.mkdir()
    _write_user_settings(tmp_path, {"scans_dir": str(custom)})
    settings._scans_dir._default = tmp_path / "sc_default"
    assert settings.get_scans_dir() == custom


def test_get_dir_corrupt_json_uses_default(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    default = tmp_path / "dl_default"
    settings._downloads_dir._default = default
    _write_user_settings(tmp_path, "{not json")
    assert settings.get_downloads_dir() == default


def test_cache_hit_does_not_reread_within_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    clock = [1000.0]
    monkeypatch.setattr(settings.time, "time", lambda: clock[0])
    first = tmp_path / "first"
    first.mkdir()
    _write_user_settings(tmp_path, {"downloads_dir": str(first)})
    settings._downloads_dir._default = tmp_path / "dl_default"
    assert settings.get_downloads_dir() == first
    second = tmp_path / "second"
    second.mkdir()
    _write_user_settings(tmp_path, {"downloads_dir": str(second)})
    clock[0] += settings._CachedDir._TTL - 0.1
    assert settings.get_downloads_dir() == first


def test_cache_recomputes_after_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    clock = [1000.0]
    monkeypatch.setattr(settings.time, "time", lambda: clock[0])
    first = tmp_path / "first"
    first.mkdir()
    _write_user_settings(tmp_path, {"downloads_dir": str(first)})
    settings._downloads_dir._default = tmp_path / "dl_default"
    assert settings.get_downloads_dir() == first
    second = tmp_path / "second"
    second.mkdir()
    _write_user_settings(tmp_path, {"downloads_dir": str(second)})
    clock[0] += settings._CachedDir._TTL + 0.1
    assert settings.get_downloads_dir() == second


def test_invalidate_forces_recompute(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    clock = [1000.0]
    monkeypatch.setattr(settings.time, "time", lambda: clock[0])
    first = tmp_path / "first"
    first.mkdir()
    _write_user_settings(tmp_path, {"downloads_dir": str(first)})
    settings._downloads_dir._default = tmp_path / "dl_default"
    assert settings.get_downloads_dir() == first
    second = tmp_path / "second"
    second.mkdir()
    _write_user_settings(tmp_path, {"downloads_dir": str(second)})
    settings.invalider_downloads_dir_cache()
    assert settings.get_downloads_dir() == second


def test_invalidate_resets_internal_state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    settings._scans_dir._default = tmp_path / "sc_default"
    settings.get_scans_dir()
    assert settings._scans_dir._val is not None
    settings.invalider_scans_dir_cache()
    assert settings._scans_dir._val is None
    assert settings._scans_dir._ts == 0.0
