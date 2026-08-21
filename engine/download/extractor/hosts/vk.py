from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="vk",
    domains=("vk.com", "vkvideo.ru", "vk.ru", "vkontakte.ru"),
    prefer_ytdlp=True,
    note="Extracteur yt-dlp natif robuste (gere ses propres en-tetes) ; pas de Referer force",
))
