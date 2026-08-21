from engine.download.methods import nm3u8dl
from engine.download.methods._nm3u8dl_parsing import construire_commande


def _adjacent(cmd, flag, value):
    return (flag, value) in [(cmd[i], cmd[i + 1]) for i in range(len(cmd) - 1)]


def _cmd(ffmpeg_path=None):
    return construire_commande(
        "EXE", "http://h/x.m3u8", "/d", "nom", "/tmp", {}, {"qualite": "auto"}, ffmpeg_path
    )


def test_ffmpeg_binary_path_pinned_when_resolved():
    cmd = _cmd("C:/bundle/bin/ffmpeg.exe")
    assert _adjacent(cmd, "--ffmpeg-binary-path", "C:/bundle/bin/ffmpeg.exe")


def test_ffmpeg_binary_path_absent_when_unresolved():
    assert "--ffmpeg-binary-path" not in _cmd(None)
    assert "--ffmpeg-binary-path" not in _cmd("")


def test_preparer_pins_bundled_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {"qualite": "auto"})
    monkeypatch.setattr(nm3u8dl, "_find_ffmpeg", lambda: "C:/bundle/bin/ffmpeg.exe")

    prep = nm3u8dl._preparer_nm3u8dl("http://h/x.m3u8", str(tmp_path), "ep", {}, None)

    assert prep is not None
    _, _, cmd, _ = prep
    idx = cmd.index("--ffmpeg-binary-path")
    assert cmd[idx + 1] == "C:/bundle/bin/ffmpeg.exe"


def test_preparer_omits_flag_when_ffmpeg_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    monkeypatch.setattr(nm3u8dl, "_get_user_settings", lambda: {"qualite": "auto"})
    monkeypatch.setattr(nm3u8dl, "_find_ffmpeg", lambda: None)

    prep = nm3u8dl._preparer_nm3u8dl("http://h/x.m3u8", str(tmp_path), "ep", {}, None)

    assert prep is not None
    _, _, cmd, _ = prep
    assert "--ffmpeg-binary-path" not in cmd
