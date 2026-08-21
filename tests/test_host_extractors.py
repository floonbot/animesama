from engine.download.extractor.registry import get_extractor


def test_sibnet_headers_and_args():
    ext = get_extractor("https://video.sibnet.ru/shellplayer.php?videoid=1")
    assert ext.name == "sibnet"
    assert ext.referer == "https://video.sibnet.ru/"
    assert ext.origin == "https://video.sibnet.ru"
    assert ext.extractor_args == "sibnet:quality=1080"

def test_vidmoly_referer_and_strategy():
    ext = get_extractor("https://vidmoly.to/embed-abc.html")
    assert ext.name == "vidmoly"
    assert ext.referer == "https://vidmoly.net/"
    assert ext.prefer_ytdlp is True

def test_sendvid_referer_and_strategy():
    ext = get_extractor("https://sendvid.com/abc")
    assert ext.name == "sendvid"
    assert ext.referer == "https://sendvid.com/"
    assert ext.prefer_ytdlp is True

def test_doodstream_variants_match():
    for url in (
        "https://doodstream.com/e/x",
        "https://dood.watch/e/x",
        "https://d000d.com/e/x",
    ):
        ext = get_extractor(url)
        assert ext.name == "doodstream", url
        assert ext.prefer_ytdlp is True
        assert ext.referer

def test_vudeo_is_new_interception_host():
    ext = get_extractor("https://vudeo.io/embed-xyz.html")
    assert ext.name == "vudeo"
    assert ext.referer == "https://vudeo.io/"
    assert ext.prefer_ytdlp is False
