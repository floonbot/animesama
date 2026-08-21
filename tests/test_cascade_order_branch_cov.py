from engine.download._domain_strategy import partition_lecteurs
from engine.download.extractor.registry import is_progressive_mp4


def test_progressive_mp4_hosts_go_last_in_ytdlp_bucket():
    lecteurs = [
        {"src": "https://video.sibnet.ru/v", "host": "sibnet"},
        {"src": "https://vidmoly.net/embed-x.html", "host": "vidmoly"},
        {"src": "https://sendvid.com/a", "host": "sendvid"},
    ]
    ytdlp, autres = partition_lecteurs(lecteurs)
    hosts = [l["host"] for l in ytdlp]
    assert set(hosts) == {"sibnet", "vidmoly", "sendvid"}
    assert hosts.index("vidmoly") < hosts.index("sibnet")
    assert hosts.index("vidmoly") < hosts.index("sendvid")


def test_progressive_mp4_relative_order_preserved():
    lecteurs = [
        {"src": "https://sendvid.com/a", "host": "sendvid"},
        {"src": "https://video.sibnet.ru/v", "host": "sibnet"},
    ]
    ytdlp, _ = partition_lecteurs(lecteurs)
    assert [l["host"] for l in ytdlp] == ["sendvid", "sibnet"]


def test_progressive_mp4_flag_on_slow_hosts():
    assert is_progressive_mp4("https://video.sibnet.ru/v") is True
    assert is_progressive_mp4("https://sendvid.com/a") is True
    assert is_progressive_mp4("https://uqload.io/x") is True
    assert is_progressive_mp4("https://www.mp4upload.com/x") is True


def test_hls_and_native_hosts_not_progressive():
    assert is_progressive_mp4("https://vidmoly.net/embed-x.html") is False
    assert is_progressive_mp4("https://streamwish.to/e/x") is False
    assert is_progressive_mp4("https://vk.com/video_x") is False
