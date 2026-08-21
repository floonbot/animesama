from engine.download._domain_strategy import partition_lecteurs, strategie_lecteur


def test_sibnet_routed_ytdlp_first_via_registry():
    assert strategie_lecteur({"src": "https://video.sibnet.ru/v"}) == "ytdlp_first"

def test_vudeo_stays_playwright_first():
    assert strategie_lecteur({"src": "https://vudeo.io/embed-x.html"}) == "playwright_first"

def test_vidmoly_now_ytdlp_first():
    for tld in ("to", "me", "net", "biz"):
        assert strategie_lecteur(
            {"src": f"https://vidmoly.{tld}/embed-x.html"}
        ) == "ytdlp_first", tld

def test_unknown_host_still_playwright_first():
    assert strategie_lecteur({"src": "https://unknown-host.tld/v"}) == "playwright_first"

def test_known_ytdlp_domain_unchanged():
    assert strategie_lecteur({"src": "https://sendvid.com/v"}) == "ytdlp_first"

def test_partition_routes_sibnet_into_ytdlp_bucket():
    ytdlp, autres = partition_lecteurs([
        {"src": "https://video.sibnet.ru/v", "host": "video.sibnet.ru"},
        {"src": "https://vudeo.io/e", "host": "vudeo.io"},
    ])
    assert [l["host"] for l in ytdlp] == ["video.sibnet.ru"]
    assert [l["host"] for l in autres] == ["vudeo.io"]
