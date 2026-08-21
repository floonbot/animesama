from engine.download.extractor.registry import get_extractor


def test_vidmoly_biz_resolves_to_vidmoly():
    ext = get_extractor("https://vidmoly.biz/embed-y6pkvt1nccib.html")
    assert ext.name == "vidmoly"
    assert ext.prefer_ytdlp is True
    assert ext.referer == "https://vidmoly.net/"


def test_vidmoly_biz_subdomain_matches():
    assert get_extractor("https://www.vidmoly.biz/embed-x.html").name == "vidmoly"


def test_vidmoly_existing_tlds_unchanged():
    for tld in ("to", "me", "net"):
        assert get_extractor(f"https://vidmoly.{tld}/embed-x.html").name == "vidmoly"
