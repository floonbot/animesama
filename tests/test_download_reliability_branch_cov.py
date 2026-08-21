from engine.download.extractor.registry import get_extractor
from engine.download.methods import _nm3u8dl_parsing, _ytdlp_parsing


def _adjacent(cmd, flag, value):
    return (flag, value) in [(cmd[i], cmd[i + 1]) for i in range(len(cmd) - 1)]


def test_nm3u8dl_segment_retry_count_is_three():
    cmd = _nm3u8dl_parsing.construire_commande(
        "EXE", "http://h/x.m3u8", "/d", "nom", "/tmp", {}, {"qualite": "auto"}
    )
    assert _adjacent(cmd, "--download-retry-count", "3")
    assert not _adjacent(cmd, "--download-retry-count", "1")


def test_sendvid_declares_no_aria2c():
    ext = get_extractor("https://sendvid.com/embed/abc")
    assert ext.name == "sendvid"
    assert ext.prefer_ytdlp is True
    assert ext.no_aria2c is True


def test_sendvid_ytdlp_command_omits_aria2c_downloader():
    cmd = _ytdlp_parsing.construire_commande(
        "yt", "https://sendvid.com/embed/abc", "/d", "n", {}, "auto", aria2c="/bin/aria2c"
    )
    assert "--downloader" not in cmd
    assert "aria2c" not in " ".join(cmd)
