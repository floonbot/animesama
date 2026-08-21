from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="lulustream",
    domains=("lulustream.com", "luluvdo.com", "lulu.st", "lulustream.to", "ludevorts.com"),
    prefer_ytdlp=True,
    referer="https://lulustream.com/",
    note="HLS (m3u8) famille streamwish ; Referer lulustream ; yt-dlp generique sinon sniff navigateur (aucun extracteur natif)",
))
