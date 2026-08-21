from engine.download.interceptor import _AD_HOSTS_RE


def test_adblock_matches_known_ad_and_tracker_hosts():
    for url in (
        "https://acscdn.com/script/aclib.js",
        "https://a-zzz.com/btag.min.js",
        "https://pagead2.googlesyndication.com/pagead/js/x.js",
        "https://www.googletagmanager.com/gtag/js?id=G-X",
        "https://www.google-analytics.com/collect",
        "https://ad.doubleclick.net/x",
        "https://hagne-puo.com/zokredirect?visitid=x",
        "https://static.cloudflareinsights.com/beacon.min.js",
        "https://cdn.hilltopads.com/x.js",
        "https://www.popcash.net/pop",
        "https://a.adsterra.com/tag",
        "https://www.highperformanceformat.com/x",
        "https://api.juicyads.com/x",
        "https://main.exoclick.com/x",
        "https://s.clickadu.com/x",
    ):
        assert _AD_HOSTS_RE.search(url), url


def test_adblock_never_matches_video_or_stream_hosts():
    for url in (
        "https://video.sibnet.ru/shell.php?videoid=1",
        "https://strm9.uqload.is/hls2/03/05352/x/master.m3u8?t=abc",
        "https://vidmoly.to/embed-59qyfgb93zvc.html",
        "https://sendvid.com/embed/xyz",
        "https://cdn.example.com/hls/index-v1.txt",
        "https://host/video/master.m3u8",
        "https://host/downloads/headers/ad-free.mp4",
    ):
        assert not _AD_HOSTS_RE.search(url), url
