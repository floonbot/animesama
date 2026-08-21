from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="mp4upload",
    domains=("mp4upload.com",),
    prefer_ytdlp=True,
    referer="https://www.mp4upload.com/",
    progressive_mp4=True,
    note="MP4 progressif ; extracteur yt-dlp generique (MP4 direct, aucun extracteur natif) ; Referer mp4upload",
))
