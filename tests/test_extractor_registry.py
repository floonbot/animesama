from engine.download.extractor.registry import (
    HostExtractor,
    extractor_args,
    get_extractor,
    host_headers,
    media_kind,
    prefer_ytdlp,
    supported_hosts,
)


def test_unknown_host_returns_generic():
    ext = get_extractor("https://unknown-host.tld/x")
    assert ext.name == "generic"
    assert ext.prefer_ytdlp is False
    assert ext.referer == ""

def test_matches_exact_and_subdomain():
    ext = get_extractor("https://video.sibnet.ru/v")
    assert ext.name == "sibnet"
    ext2 = get_extractor("sibnet.ru")
    assert ext2.name == "sibnet"

def test_get_extractor_accepts_bare_host_and_netloc_with_port():
    assert get_extractor("sendvid.com").name == "sendvid"
    assert get_extractor("sendvid.com:443").name == "sendvid"

def test_host_headers_generic_passthrough():
    base = {"referer": "https://anime-sama.to/", "user-agent": "UA"}
    out = host_headers("https://unknown-host.tld/x", base)
    assert out == base
    assert out is not base

def test_host_headers_forces_sibnet_referer_over_base():
    base = {"referer": "https://anime-sama.to/"}
    out = host_headers("https://video.sibnet.ru/v", base)
    assert out["referer"] == "https://video.sibnet.ru/"
    assert out["origin"] == "https://video.sibnet.ru"

def test_prefer_ytdlp_reflects_host_flag():
    assert prefer_ytdlp("https://video.sibnet.ru/v") is True
    assert prefer_ytdlp("https://unknown-host.tld/v") is False

def test_extractor_args_for_sibnet():
    assert extractor_args("https://video.sibnet.ru/v") == "sibnet:quality=1080"
    assert extractor_args("https://unknown-host.tld/v") == ""

def test_supported_hosts_contains_new_hosts():
    names = {h["name"] for h in supported_hosts()}
    assert {"sibnet", "vidmoly", "sendvid", "doodstream", "vudeo"} <= names

def test_supported_hosts_entries_have_shape():
    for h in supported_hosts():
        assert set(h) == {"name", "domains", "strategy", "note"}
        assert h["strategy"] in ("yt-dlp", "playwright")
        assert isinstance(h["domains"], list) and h["domains"]

def test_media_kind_delegates_to_patterns():
    assert media_kind("https://cdn/master.m3u8") == "hls"
    assert media_kind("https://cdn/v.mp4") == "mp4"
    assert media_kind("https://host/index.html") is None

def test_register_is_idempotent_safe_for_duplicates():
    before = len(supported_hosts())
    get_extractor("https://video.sibnet.ru/v")
    after = len(supported_hosts())
    assert after == before

def test_host_extractor_matches_helper():
    ext = HostExtractor(name="x", domains=("foo.com",))
    assert ext.matches("foo.com") is True
    assert ext.matches("a.foo.com") is True
    assert ext.matches("notfoo.com") is False
    assert ext.matches("") is False

def test_canonical_host_maps_cdn_mirrors_to_registry_name():
    from engine.download.extractor.registry import canonical_host
    assert canonical_host("https://d000d.com/e/x") == "doodstream"
    assert canonical_host("dood.watch") == "doodstream"
    assert canonical_host("video.sibnet.ru") == "sibnet"

def test_canonical_host_unknown_returns_bare_hostname():
    from engine.download.extractor.registry import canonical_host
    assert canonical_host("https://weird.unknown.tld/x") == "weird.unknown.tld"
    assert canonical_host("plain.host.tld") == "plain.host.tld"
    assert canonical_host("") == ""
