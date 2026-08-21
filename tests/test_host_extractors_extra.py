from engine.download._domain_strategy import strategie_lecteur
from engine.download.extractor.registry import get_extractor, supported_hosts


def test_new_embed_hosts_have_referer_and_ytdlp_strategy():
    cases = {
        "streamtape": "https://streamtape.com/e/abc",
        "filemoon": "https://filemoon.sx/e/abc",
    }
    for name, url in cases.items():
        ext = get_extractor(url)
        assert ext.name == name, url
        assert ext.prefer_ytdlp is True
        assert ext.referer, name


def test_uqload_garde_son_referer_sans_la_strategie_ytdlp():
    """uqload est sorti de ce lot le 12/08/2026 : Cloudflare rend une page de
    challenge que yt-dlp compte pour un succes. Voir test_uqload_interception."""
    ext = get_extractor("https://uqload.io/embed-x.html")
    assert ext.name == "uqload"
    assert ext.referer
    assert ext.prefer_ytdlp is False

def test_vk_and_ok_registered_ytdlp_native():
    assert get_extractor("https://vk.com/video123").name == "vk"
    assert get_extractor("https://vkvideo.ru/video1").name == "vk"
    assert get_extractor("https://ok.ru/video/1").name == "ok"
    for url in ("https://vk.com/x", "https://ok.ru/x"):
        assert get_extractor(url).prefer_ytdlp is True

def test_streamtape_subdomains_and_tlds_match():
    for url in (
        "https://streamtape.com/e/x",
        "https://streamtape.net/e/x",
        "https://streamta.pe/e/x",
    ):
        assert get_extractor(url).name == "streamtape", url

def test_supported_hosts_now_lists_ten():
    names = {h["name"] for h in supported_hosts()}
    expected = {
        "sibnet", "vidmoly", "sendvid", "doodstream", "vudeo",
        "streamtape", "uqload", "filemoon", "vk", "ok",
    }
    assert expected <= names

def test_strategy_unchanged_for_known_ytdlp_domains():
    for url in ("https://streamtape.com/e/x", "https://vk.com/x", "https://ok.ru/x"):
        assert strategie_lecteur({"src": url}) == "ytdlp_first"
