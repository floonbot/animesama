from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="vidhide",
    domains=(
        "vidhide.com", "vidhidepro.com", "vidhidevip.com", "vidhidehub.com",
        "filelions.to", "filelions.com", "filelions.live", "filelions.online",
        "alions.pro", "smoothpre.com",
    ),
    prefer_ytdlp=False,
    referer="https://vidhide.com/",
    note="HLS (filelions/vidhide) jwplayer packe ; yt-dlp echoue (Unsupported URL) -> sniff navigateur d'abord ; Referer vidhide",
))
