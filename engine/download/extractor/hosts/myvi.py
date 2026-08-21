from engine.download.extractor.registry import HostExtractor, register

register(HostExtractor(
    name="myvi",
    domains=("myvi.ru", "myvi.tv", "myvi.top"),
    prefer_ytdlp=True,
    referer="https://myvi.ru/",
    # Sa chaine est complete et valide, mais elle est emise par « YE2 », un
    # intermediaire Google dont la racine manque au certifi de yt-dlp (verifie
    # avec certifi 2026.07.22, donc ce n'est pas un trousseau perime). Windows
    # la connait. Sans ce drapeau, tout episode dont myvi est le lecteur echoue
    # sur CERTIFICATE_VERIFY_FAILED.
    sans_certifi=True,
    note="Hébergeur russe ; yt-dlp generique sinon sniff navigateur (aucun extracteur natif) ; Referer myvi",
))
