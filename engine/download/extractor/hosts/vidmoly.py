from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="vidmoly",
    domains=("vidmoly.to", "vidmoly.me", "vidmoly.net", "vidmoly.biz"),
    prefer_ytdlp=True,
    referer="https://vidmoly.net/",
    note="HLS (m3u8) : extracteur yt-dlp generique OK sur vidmoly.net (les .to/.me/.biz sont reecrits en .net pour l'appel yt-dlp) ; sniff navigateur .to en secours ; Referer vidmoly obligatoire pour le flux",
))
