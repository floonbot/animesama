from engine.download.extractor.registry import get_extractor, supported_hosts


def test_swishclone_domains_resolve():
    for d in ("dingtezuni.com", "minochinos.com", "movearnpre.com", "callistanise.com"):
        ext = get_extractor(f"https://{d}/embed/abc")
        assert ext.name == "swishclone", d
        assert ext.prefer_ytdlp is False, d


def test_swishclone_uses_browser_strategy():
    hosts = {h["name"]: h for h in supported_hosts()}
    assert hosts["swishclone"]["strategy"] == "playwright"


def test_swishclone_unknown_domain_stays_generic():
    assert get_extractor("https://example.org/embed/abc").name == "generic"
