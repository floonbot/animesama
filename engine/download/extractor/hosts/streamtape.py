from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="streamtape",
    domains=(
        "streamtape.com", "streamtape.net", "streamtape.to", "streamtape.xyz",
        "streamta.pe", "streamtape.site", "streamadblockplus.com", "tapewithadblock.org",
    ),
    prefer_ytdlp=True,
    referer="https://streamtape.com/",
    note="Lien direct obfusque dans le DOM ; Referer streamtape ; yt-dlp generique sinon sniff navigateur (aucun extracteur natif)",
))
