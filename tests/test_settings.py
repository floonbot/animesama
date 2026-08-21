import engine.config.user_settings as st


def test_load_defaults_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "s.json")
    out = st.load_settings()
    assert out == st.DEFAULT_SETTINGS
    assert out is not st.DEFAULT_SETTINGS

def test_save_then_load_merges_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "s.json")
    assert st.save_settings({"qualite": "720"}) is True
    out = st.load_settings()
    assert out["qualite"] == "720"
    assert out["thread_count"] == 16

def test_load_corrupt_non_dict_returns_defaults(tmp_path, monkeypatch):
    f = tmp_path / "s.json"
    f.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(st, "SETTINGS_FILE", f)
    assert st.load_settings() == st.DEFAULT_SETTINGS

def test_load_invalid_json_returns_defaults(tmp_path, monkeypatch):
    f = tmp_path / "s.json"
    f.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(st, "SETTINGS_FILE", f)
    assert st.load_settings() == st.DEFAULT_SETTINGS

def test_save_creates_parent_and_file(tmp_path, monkeypatch):
    f = tmp_path / "sub" / "dir" / "s.json"
    monkeypatch.setattr(st, "SETTINGS_FILE", f)
    assert st.save_settings({"a": 1}) is True
    assert f.exists()

def test_save_settings_restricts_file_permissions(tmp_path, monkeypatch):
    import os

    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "s.json")
    modes: list[int] = []
    real_chmod = os.chmod

    def _spy(path, mode, *a, **k):
        modes.append(mode)
        return real_chmod(path, mode, *a, **k)

    monkeypatch.setattr(os, "chmod", _spy)
    assert st.save_settings({"a": 1}) is True
    assert 0o600 in modes
