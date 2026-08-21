import sys

import engine.config.settings as settings_mod
import engine.download.methods.ffmpeg_engine as ffmpeg_engine
import engine.download.methods.nm3u8dl as nm3u8dl
import engine.download.methods.ytdlp_engine as ytdlp_engine


def _make_bundle(tmp_path, exe_name):
    bundle = tmp_path / "_internal"
    (bundle / "bin").mkdir(parents=True)
    target = bundle / "bin" / exe_name
    target.write_bytes(b"x")
    root = tmp_path / "app"
    root.mkdir()
    return bundle, root, target


def test_find_nm3u8dl_uses_bundle_bin_when_frozen(monkeypatch, tmp_path):
    bundle, root, target = _make_bundle(tmp_path, "N_m3u8DL-RE.exe")
    monkeypatch.setattr(settings_mod, "ROOT_DIR", root)
    monkeypatch.setattr(settings_mod, "_BUNDLE_DIR", bundle)
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda n: None)
    monkeypatch.setattr(nm3u8dl.sys, "argv", ["AnimeSama"])
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert nm3u8dl._find_nm3u8dl() == str(target)


def test_find_exe_uses_bundle_bin_when_frozen(monkeypatch, tmp_path):
    bundle, root, target = _make_bundle(tmp_path, "yt-dlp.exe")
    monkeypatch.setattr(settings_mod, "ROOT_DIR", root)
    monkeypatch.setattr(settings_mod, "_BUNDLE_DIR", bundle)
    monkeypatch.setattr(ytdlp_engine.shutil, "which", lambda n: None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert ytdlp_engine._find_exe(["yt-dlp.exe", "yt-dlp"]) == str(target)


def test_find_ffmpeg_uses_bundle_bin_when_frozen(monkeypatch, tmp_path):
    bundle, root, target = _make_bundle(tmp_path, "ffmpeg.exe")
    monkeypatch.setattr(settings_mod, "ROOT_DIR", root)
    monkeypatch.setattr(settings_mod, "_BUNDLE_DIR", bundle)
    monkeypatch.setattr(ffmpeg_engine.shutil, "which", lambda n: None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert ffmpeg_engine._find_ffmpeg() == str(target)


def test_find_exe_ignores_bundle_bin_when_not_frozen(monkeypatch, tmp_path):
    bundle, root, _target = _make_bundle(tmp_path, "yt-dlp.exe")
    monkeypatch.setattr(settings_mod, "ROOT_DIR", root)
    monkeypatch.setattr(settings_mod, "_BUNDLE_DIR", bundle)
    monkeypatch.setattr(ytdlp_engine.shutil, "which", lambda n: None)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert ytdlp_engine._find_exe(["yt-dlp.exe", "yt-dlp"]) is None


def _bundle_with_chromium(tmp_path):
    browsers = tmp_path / "ms-playwright"
    (browsers / "chromium-1223").mkdir(parents=True)
    return browsers


def test_browsers_path_not_set_when_not_frozen(tmp_path):
    _bundle_with_chromium(tmp_path)
    env: dict[str, str] = {}

    res = settings_mod._configure_playwright_browsers_path(tmp_path, False, env)

    assert res is None
    assert "PLAYWRIGHT_BROWSERS_PATH" not in env


def test_browsers_path_not_set_when_chromium_absent(tmp_path):
    (tmp_path / "ms-playwright").mkdir()
    env: dict[str, str] = {}

    res = settings_mod._configure_playwright_browsers_path(tmp_path, True, env)

    assert res is None
    assert "PLAYWRIGHT_BROWSERS_PATH" not in env


def test_browsers_path_set_when_frozen_and_bundled(tmp_path):
    browsers = _bundle_with_chromium(tmp_path)
    env: dict[str, str] = {}

    res = settings_mod._configure_playwright_browsers_path(tmp_path, True, env)

    assert res == str(browsers)
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(browsers)


def test_browsers_path_respects_existing_env(tmp_path):
    _bundle_with_chromium(tmp_path)
    env = {"PLAYWRIGHT_BROWSERS_PATH": "/custom"}

    res = settings_mod._configure_playwright_browsers_path(tmp_path, True, env)

    assert res == "/custom"
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == "/custom"


def test_bundled_chromium_present_helper(monkeypatch, tmp_path):
    _bundle_with_chromium(tmp_path)
    monkeypatch.setattr(settings_mod, "_BUNDLE_DIR", tmp_path)
    assert settings_mod.bundled_chromium_present() is True

    monkeypatch.setattr(settings_mod, "_BUNDLE_DIR", tmp_path / "nope")
    assert settings_mod.bundled_chromium_present() is False


def test_bundled_chromium_present_ignores_files(monkeypatch, tmp_path):
    browsers = tmp_path / "ms-playwright"
    browsers.mkdir()
    (browsers / "chromium.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(settings_mod, "_BUNDLE_DIR", tmp_path)
    assert settings_mod.bundled_chromium_present() is False


def test_browsers_path_ignores_chromium_file(tmp_path):
    browsers = tmp_path / "ms-playwright"
    browsers.mkdir()
    (browsers / "chromium.txt").write_text("x", encoding="utf-8")
    env: dict[str, str] = {}

    assert settings_mod._configure_playwright_browsers_path(tmp_path, True, env) is None
    assert "PLAYWRIGHT_BROWSERS_PATH" not in env


def test_bin_path_not_touched_when_not_frozen(tmp_path):
    (tmp_path / "bin").mkdir()
    env = {"PATH": "/usr/bin"}

    assert settings_mod._configure_bundled_bin_path(tmp_path, False, env) is False
    assert env["PATH"] == "/usr/bin"


def test_bin_path_not_touched_when_bin_absent(tmp_path):
    env = {"PATH": "/usr/bin"}

    assert settings_mod._configure_bundled_bin_path(tmp_path, True, env) is False
    assert env["PATH"] == "/usr/bin"


def test_bin_path_prepended_when_frozen(tmp_path):
    import os

    bindir = tmp_path / "bin"
    bindir.mkdir()
    env = {"PATH": "/usr/bin"}

    assert settings_mod._configure_bundled_bin_path(tmp_path, True, env) is True
    parts = env["PATH"].split(os.pathsep)
    assert parts[0] == str(bindir)
    assert "/usr/bin" in parts


def test_bin_path_not_duplicated(tmp_path):
    import os

    bindir = tmp_path / "bin"
    bindir.mkdir()
    env = {"PATH": os.pathsep.join([str(bindir), "/usr/bin"])}

    settings_mod._configure_bundled_bin_path(tmp_path, True, env)
    assert env["PATH"].split(os.pathsep).count(str(bindir)) == 1
