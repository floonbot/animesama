from engine.download.extractor.registry import get_extractor


def test_oneupload_registered():
    ext = get_extractor("https://oneupload.to/embed-fa3bfw24qud9.html")
    assert ext.name == "oneupload"
    assert ext.prefer_ytdlp is False
    assert ext.referer == "https://oneupload.to/"


def test_oneupload_variants_match():
    for host in ("oneupload.net", "oneupload.cc", "oneupload.stream"):
        assert get_extractor(f"https://{host}/embed-x.html").name == "oneupload"
