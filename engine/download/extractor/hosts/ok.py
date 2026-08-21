from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="ok",
    domains=("ok.ru", "odnoklassniki.ru"),
    prefer_ytdlp=True,
    note="Extracteur yt-dlp natif (Odnoklassniki) ; pas de Referer force",
))
