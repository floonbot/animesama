from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="streamwish",
    domains=(
        "streamwish.com", "streamwish.to", "embedwish.com", "wishfast.top",
        "awish.pro", "dwish.pro", "mwish.pro", "hlswish.com", "swishsrv.com",
        "wishonly.site",
    ),
    prefer_ytdlp=True,
    referer="https://streamwish.com/",
    note="HLS (m3u8) ; Referer streamwish obligatoire ; yt-dlp generique sinon sniff navigateur (aucun extracteur natif)",
))
