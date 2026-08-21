from engine.download.extractor.registry import HostExtractor, register

# Passe par l'interception et non par yt-dlp. Fait observe le 12/08/2026 a
# 17:14 sur uqload.is : yt-dlp sort en code 0 sans produire de fichier —
# « Processus OK mais fichier introuvable » — soit trois secondes gaspillees a
# chaque episode dont uqload est lecteur.
#
# Le mecanisme exact n'est PAS etabli. Une sonde du 12/08 a 18:20 rend 200 et
# une page normale sur .io, .com, .net, .co et .is, sans marqueur de challenge ;
# les adresses sont bien dans les plages Cloudflare, mais rien ne prouve qu'une
# page de defi soit servie. Ce qui est certain : uqload n'a aucun extracteur
# natif yt-dlp, donc le chemin direct ne valait que si le MP4 etait joignable
# tel quel — et il ne l'est pas. Le navigateur execute le lecteur, lui.
#
# .to ne resout plus (getaddrinfo echoue sur le resolveur systeme comme sur
# 8.8.8.8). Il reste declare : le domaine peut revenir, et un domaine mort ne
# coute qu'une resolution DNS ratee.
register(HostExtractor(
    name="uqload",
    domains=("uqload.io", "uqload.to", "uqload.com", "uqload.net", "uqload.co", "uqload.x", "uqload.is"),
    referer="https://uqload.io/",
    progressive_mp4=True,
    note="MP4 progressif derriere Cloudflare ; Referer uqload obligatoire ; interception navigateur (aucun extracteur natif yt-dlp)",
))
