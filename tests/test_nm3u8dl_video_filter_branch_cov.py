import os

from engine.download.methods import nm3u8dl
from engine.download.methods._nm3u8dl_parsing import construire_commande


def test_find_ffmpeg_prefers_bin_over_path(monkeypatch):
    from engine.config import settings

    fake_bin = os.path.join(str(settings.ROOT_DIR), "bin", "ffmpeg.exe")
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda _n: "C:/system/ffmpeg.exe")
    monkeypatch.setattr(
        nm3u8dl.os.path, "exists", lambda p: os.path.normpath(p) == os.path.normpath(fake_bin)
    )
    assert os.path.normpath(nm3u8dl._find_ffmpeg()) == os.path.normpath(fake_bin)


def test_find_ffmpeg_falls_back_to_path_when_bin_absent(monkeypatch):
    monkeypatch.setattr(nm3u8dl.os.path, "exists", lambda _p: False)
    monkeypatch.setattr(nm3u8dl.shutil, "which", lambda _n: "C:/system/ffmpeg.exe")
    assert nm3u8dl._find_ffmpeg() == "C:/system/ffmpeg.exe"


def _cmd(qualite):
    return construire_commande(
        "EXE", "http://h/x.m3u8", "/dossier", "nom", "/tmp", {}, {"qualite": qualite}
    )


def test_quality_filter_uses_valid_select_video_flag():
    for q in ("1080", "720", "480"):
        cmd = _cmd(q)
        assert "-sv" in cmd
        idx = cmd.index("-sv")
        assert cmd[idx + 1] == f"res=x{q}:for=best"


def test_res_filter_anchored_on_height_not_width():
    """res=x<H> ancre sur la hauteur (WIDTHxHEIGHT) — evite que res=720 matche la
    LARGEUR de 720x480 (SD) au lieu d'un vrai 720p."""
    for q in ("1080", "720", "480"):
        cmd = _cmd(q)
        idx = cmd.index("-sv")
        assert cmd[idx + 1].startswith(f"res=x{q}")
        assert f"res={q}:" not in cmd[idx + 1]


def test_quality_filter_also_selects_audio():
    for q in ("1080", "720", "480"):
        cmd = _cmd(q)
        assert "-sa" in cmd
        idx = cmd.index("-sa")
        assert cmd[idx + 1] == "best"


def test_obsolete_video_filter_flag_never_emitted():
    for q in ("1080", "720", "480", "auto", "bad"):
        cmd = _cmd(q)
        assert "--video-filter" not in cmd


def test_auto_quality_keeps_auto_select():
    cmd = _cmd("auto")
    assert "--auto-select" in cmd
    assert "-sv" not in cmd
