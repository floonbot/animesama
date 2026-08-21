"""Regression: _CachedDir.get must not crash on a malformed user_settings.json.

`get_downloads_dir()` / `get_scans_dir()` are called across the scanner,
download pipeline, worker and health routes. Previously `_CachedDir.get` only
caught (OSError, json.JSONDecodeError), so a *valid*-JSON-but-non-dict file
(``[]`` / ``null`` / ``5``) — or a dict whose value isn't a string — raised an
uncaught AttributeError/TypeError and crashed those paths. The sibling
`user_settings.load_settings` already guards `isinstance(data, dict)`.
"""

import json

import pytest

import engine.config.settings as settings


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    settings.invalider_downloads_dir_cache()
    settings.invalider_scans_dir_cache()
    settings._downloads_dir._default = tmp_path / "dl_default"
    settings._scans_dir._default = tmp_path / "sc_default"
    yield tmp_path
    settings.invalider_downloads_dir_cache()
    settings.invalider_scans_dir_cache()


def _write(path, raw_text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw_text, encoding="utf-8")


@pytest.mark.parametrize("payload", ["[]", "null", "5", '"downloads"', "[1, 2, 3]"])
def test_non_dict_settings_falls_back_to_default(tmp_data, payload):
    _write(tmp_data / "user_settings.json", payload)
    assert settings.get_downloads_dir() == settings._downloads_dir._default


def test_non_string_dir_value_falls_back_to_default(tmp_data):
    _write(tmp_data / "user_settings.json", json.dumps({"downloads_dir": 5}))
    assert settings.get_downloads_dir() == settings._downloads_dir._default


def test_valid_string_dir_still_honoured(tmp_data):
    target = tmp_data / "dl_custom"
    target.mkdir()
    _write(tmp_data / "user_settings.json", json.dumps({"downloads_dir": str(target)}))
    assert settings.get_downloads_dir() == target
