from engine.config.settings import YTDLP_FIRST_DOMAINS
from engine.download.extractor.registry import get_extractor, supported_hosts


def test_every_ytdlp_first_domain_has_a_registry_extractor():
    """Parité : chaque domaine déclaré yt-dlp-first résout vers un extracteur dédié (jamais 'generic')."""
    manquants = [
        d for d in YTDLP_FIRST_DOMAINS
        if get_extractor("https://" + d + "/x").name == "generic"
    ]
    assert manquants == [], f"domaines sans module registre : {manquants}"

def test_myvi_registered():
    ext = get_extractor("https://myvi.ru/embed/abc")
    assert ext.name == "myvi"
    assert ext.prefer_ytdlp is True
    assert ext.referer

def test_supported_hosts_reaches_fifteen():
    assert len({h["name"] for h in supported_hosts()}) >= 15
