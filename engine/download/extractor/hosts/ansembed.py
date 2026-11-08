from engine.download.extractor.registry import HostExtractor, register

# Lecteur propre a anime-sama, apparu avec la refonte du site : releve le
# 08/11/2026 sur 57 oeuvres sur 60 echantillonnees (345 liens de lecteur, le
# premier hebergeur du site). C'est un vidmoly a la marque du site — ressources
# servies par cdn.staticmoly.me, script « anime-sama-intro » — et la page porte
# le master.m3u8 en clair (480p et 1080p, CDN *.vmnow.online).
#
# Sans module, il tombait sur l'extracteur generique : interception par le
# navigateur, donc rien sans Chromium. L'extracteur generique de yt-dlp le lit
# tel quel : 1080p, 754 Mo en 17 s au banc, autant que N_m3u8DL-RE sur le flux
# intercepte.
register(HostExtractor(
    name="ansembed",
    domains=("ansembed.net",),
    prefer_ytdlp=True,
    referer="https://ansembed.net/",
    note="HLS (vidmoly a la marque d'anime-sama) ; m3u8 en clair dans la page, extracteur yt-dlp generique ; Referer ansembed",
))
