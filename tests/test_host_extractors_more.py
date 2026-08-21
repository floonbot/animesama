from engine.download._domain_strategy import strategie_lecteur
from engine.download.extractor.registry import get_extractor, supported_hosts


def test_new_hosts_registered_with_referer_and_ytdlp():
    cases = {
        "mp4upload": "https://www.mp4upload.com/embed-abc.html",
        "lulustream": "https://lulustream.com/e/xyz",
        "streamwish": "https://streamwish.com/e/xyz",
    }
    for name, url in cases.items():
        ext = get_extractor(url)
        assert ext.name == name, url
        assert ext.prefer_ytdlp is True
        assert ext.referer, name

def test_vidhide_is_sniff_first():
    ext = get_extractor("https://vidhide.com/embed/xyz")
    assert ext.name == "vidhide"
    assert ext.prefer_ytdlp is False
    assert ext.referer
    assert strategie_lecteur({"src": "https://vidhide.com/x"}) == "playwright_first"

def test_family_subdomains_and_aliases_match():
    assert get_extractor("https://luluvdo.com/e/x").name == "lulustream"
    assert get_extractor("https://filelions.to/v/x").name == "vidhide"
    assert get_extractor("https://embedwish.com/e/x").name == "streamwish"
    assert get_extractor("https://cdn.mp4upload.com/x").name == "mp4upload"

def test_supported_hosts_count_reaches_fourteen():
    names = {h["name"] for h in supported_hosts()}
    new = {"mp4upload", "lulustream", "vidhide", "streamwish"}
    assert new <= names
    assert len(names) >= 14

def test_new_hosts_route_ytdlp_first():
    for url in (
        "https://mp4upload.com/x",
        "https://lulustream.com/x",
        "https://streamwish.com/x",
    ):
        assert strategie_lecteur({"src": url}) == "ytdlp_first"
