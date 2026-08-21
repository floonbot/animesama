"""Regression : uqload doit passer par l'interception, pas par yt-dlp direct.

Fait observe, journal du 12/08/2026 :

    17:14:17  [yt-dlp] Telechargement : Youjo Senki - S02E006 (uqload.is)
    17:14:20  [yt-dlp] Processus OK mais fichier introuvable

Code retour 0, aucun fichier : trois secondes gaspillees a chaque episode dont
uqload est lecteur. uqload n'a aucun extracteur natif yt-dlp — le chemin direct
ne valait que si le MP4 etait joignable tel quel. Le mecanisme precis de
l'echec n'est pas etabli ; voir le commentaire de hosts/uqload.py.

Le piege que ce test verrouille : la strategie se decide a **deux** endroits.
`strategie_lecteur` consulte d'abord `YTDLP_FIRST_DOMAINS`, et seulement ensuite
le drapeau `prefer_ytdlp` du registre. Retirer le seul drapeau laissait
`uqload.io` et `uqload.to` dans le mauvais seau — soit deux domaines sur trois
parmi ceux que le site sert reellement.
"""

from engine.config.settings import YTDLP_FIRST_DOMAINS
from engine.download._domain_strategy import partition_lecteurs, strategie_lecteur
from engine.download.extractor.registry import get_extractor

DOMAINES = ("uqload.io", "uqload.to", "uqload.com", "uqload.net", "uqload.co", "uqload.is")


def test_aucun_domaine_uqload_ne_part_sur_ytdlp():
    for d in DOMAINES:
        lecteur = {"src": f"https://{d}/embed-abc123.html", "host": "uqload"}
        assert strategie_lecteur(lecteur) == "playwright_first", d


def test_les_deux_mecanismes_sont_desarmes():
    """Le drapeau du registre ET la liste des domaines : les deux, ou rien."""
    assert get_extractor("https://uqload.is/x").prefer_ytdlp is False
    for d in DOMAINES:
        assert d not in YTDLP_FIRST_DOMAINS, d


def test_uqload_atterrit_dans_le_seau_interception():
    lecteurs = [
        {"src": "https://uqload.is/embed-a.html", "host": "uqload"},
        {"src": "https://video.sibnet.ru/shell.php?videoid=1", "host": "sibnet"},
    ]
    ytdlp, autres = partition_lecteurs(lecteurs)
    assert [l["host"] for l in ytdlp] == ["sibnet"]
    assert [l["host"] for l in autres] == ["uqload"]


def test_le_referer_et_le_mp4_progressif_survivent():
    """Retirer prefer_ytdlp ne doit pas emporter le reste de la configuration."""
    ext = get_extractor("https://uqload.is/embed-a.html")
    assert ext.referer == "https://uqload.io/"
    assert ext.progressive_mp4 is True


def test_uqload_n_est_pas_declare_mort():
    """Declasser n'est pas condamner : si l'interception passe, il resert."""
    from engine.config.settings import HOSTS_MORTS

    for d in DOMAINES:
        assert d not in HOSTS_MORTS, d
