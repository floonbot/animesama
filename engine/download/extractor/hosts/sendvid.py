from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="sendvid",
    domains=("sendvid.com",),
    prefer_ytdlp=True,
    referer="https://sendvid.com/",
    no_aria2c=True,
    progressive_mp4=True,
    note="MP4 progressif + HLS de secours ; extracteur yt-dlp generique (MP4 direct, aucun extracteur natif) ; hote fragile (rate-limit 5s/penalite 60s) : downloader natif yt-dlp, pas d'aria2c multi-connexion",
))
