from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="sibnet",
    domains=("sibnet.ru",),
    prefer_ytdlp=True,
    referer="https://video.sibnet.ru/",
    origin="https://video.sibnet.ru",
    extractor_args="sibnet:quality=1080",
    no_aria2c=True,
    progressive_mp4=True,
    note="MP4 direct ; Referer/Origin obligatoires ; extracteur yt-dlp natif ; CDN dvXX rejette le multi-connexion aria2c (400)",
))
