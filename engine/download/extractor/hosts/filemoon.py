from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="filemoon",
    domains=(
        "filemoon.sx", "filemoon.to", "filemoon.in", "filemoon.nl",
        "filemoon.eu", "filemoon.link", "moonplayer.site", "kerapoxy.cc",
    ),
    prefer_ytdlp=True,
    referer="https://filemoon.sx/",
    note="HLS (m3u8) packe/obfusque ; Referer filemoon ; yt-dlp generique sinon sniff navigateur (aucun extracteur natif)",
))
