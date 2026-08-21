from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="doodstream",
    domains=(
        "doodstream.com", "dood.watch", "dood.to", "dood.so", "dood.ws",
        "dood.la", "dood.pm", "dood.re", "dood.yt", "dooood.com",
        "ds2play.com", "ds2video.com", "d000d.com", "d0000d.com", "d0o0d.com",
    ),
    prefer_ytdlp=True,
    referer="https://dood.watch/",
    note="Lien CDN signe a duree de vie courte ; Referer dood obligatoire ; yt-dlp generique sinon sniff navigateur (aucun extracteur natif)",
))
