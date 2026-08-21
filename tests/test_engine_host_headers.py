from engine.download.methods._ffmpeg_parsing import (
    construire_commande as ffmpeg_cmd,
)
from engine.download.methods._nm3u8dl_parsing import (
    construire_commande as nm3u8dl_cmd,
)
from engine.download.methods._ytdlp_parsing import (
    construire_commande as ytdlp_cmd,
)


def test_ytdlp_injects_registry_referer_for_vidmoly():
    c = ytdlp_cmd("yt", "https://vidmoly.to/embed-x.html", "/d", "n", {}, "auto")
    assert "--referer" in c
    assert "https://vidmoly.net/" in c

def test_ytdlp_host_referer_overrides_captured():
    c = ytdlp_cmd("yt", "https://video.sibnet.ru/v", "/d", "n", {"referer": "http://wrong"}, "auto")
    assert "https://video.sibnet.ru/" in c
    assert "http://wrong" not in c

def test_ytdlp_sibnet_still_has_origin_and_extractor_args():
    c = ytdlp_cmd("yt", "https://video.sibnet.ru/v", "/d", "n", {}, "auto")
    assert "Origin:https://video.sibnet.ru" in c
    assert "--extractor-args" in c and "sibnet:quality=1080" in c

def test_ytdlp_generic_host_unaffected_referer_passthrough():
    c = ytdlp_cmd("yt", "http://h/v", "/d", "n", {"referer": "http://r"}, "auto")
    assert "http://r" in c

def test_nm3u8dl_injects_registry_referer_when_stream_host_matches():
    c = nm3u8dl_cmd("EXE", "https://video.sibnet.ru/v/file.mp4", "/d", "n", "/tmp", {}, {})
    assert any(h == "Referer: https://video.sibnet.ru/" for h in c)

def test_nm3u8dl_generic_no_referer_with_empty_headers():
    c = nm3u8dl_cmd("EXE", "http://h/x.m3u8", "/d", "n", "/tmp", {}, {})
    assert not any(h.startswith("Referer:") for h in c)

def test_ffmpeg_injects_registry_referer_for_vudeo():
    c = ffmpeg_cmd("ff", "https://vudeo.io/file.mp4", "/o.mp4", {})
    assert "-referer" in c and "https://vudeo.io/" in c

def test_ffmpeg_generic_no_referer_with_empty_headers():
    c = ffmpeg_cmd("ff", "http://h/x.m3u8", "/o.mp4", {})
    assert "-referer" not in c

def test_ffmpeg_injects_registry_origin_for_sibnet():
    c = ffmpeg_cmd("ff", "https://video.sibnet.ru/v/file.mp4", "/o.mp4", {})
    assert any("Origin: https://video.sibnet.ru" in h for h in c)

def test_ffmpeg_no_registry_origin_for_generic_host():
    c = ffmpeg_cmd("ff", "http://h/x.m3u8", "/o.mp4", {})
    assert not any("Origin:" in h for h in c)

def test_nm3u8dl_injects_registry_origin_for_sibnet():
    c = nm3u8dl_cmd("EXE", "https://video.sibnet.ru/v/file.mp4", "/d", "n", "/tmp", {}, {})
    assert any(h == "Origin: https://video.sibnet.ru" for h in c)

def test_nm3u8dl_no_registry_origin_for_generic_host():
    c = nm3u8dl_cmd("EXE", "http://h/x.m3u8", "/d", "n", "/tmp", {}, {})
    assert not any(h.startswith("Origin:") for h in c)
