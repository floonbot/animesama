from engine.download.extractor.registry import HostExtractor, register
from engine.scraping.site.animessama import SITE_URL

register(HostExtractor(
    name="swishclone",
    domains=("dingtezuni.com", "minochinos.com", "movearnpre.com", "callistanise.com"),
    prefer_ytdlp=False,
    referer=SITE_URL + "/",
    note="HLS (m3u8) via lecteur jwplayer/eval-packed ; reseau de domaines tournants "
         "(clone StreamWish, backend callistanise.com partage, chemin /stream/<tok>/.../master.m3u8) "
         "non reconnu par yt-dlp → capture par interception navigateur ; Referer page accepte par le flux",
))
