"""Regression : myvi.tv echoue sur son certificat avec le certifi de yt-dlp.

Sa chaine est complete et valide — le serveur envoie bien ses trois certificats —
mais l'intermediaire emetteur (« YE2 », Google Trust Services) a une racine
absente du trousseau certifi 2026.07.22 qu'embarque yt-dlp. Le magasin de
Windows la connait. Mesure a l'appui, sur https://www.myvi.tv/ :

    temoin                       CERTIFICATE_VERIFY_FAILED
    --compat-options no-certifi  page telechargee
    --no-check-certificates      page telechargee, mais plus aucune verification

`no-certifi` change de magasin sans rien desactiver, et c'est celui du systeme,
tenu a jour par Windows Update.

Pourquoi par hote et jamais globalement : les 27 hotes connus de l'application
ont ete verifies contre les deux trousseaux. Le magasin Windows repare myvi.tv,
mais il ignore les racines de vk.com, vkvideo.ru et ok.ru, que certifi couvre.
Un drapeau global reparerait un hebergeur et en casserait trois — dont vk, qui
est souvent le premier lecteur propose.
"""

from engine.download.extractor.registry import get_extractor
from engine.download.methods._ytdlp_parsing import construire_commande


def _cmd(url):
    return construire_commande("yt", url, "/d", "n", {}, "auto")


def _compat(cmd):
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == "--compat-options"]


def test_myvi_utilise_le_magasin_du_systeme():
    assert _compat(_cmd("https://www.myvi.tv/embed/abc")) == ["no-certifi"]


def test_les_autres_hotes_gardent_certifi():
    # vk et ok en tete : ce sont eux que le drapeau global aurait casses.
    for url in (
        "https://vk.com/video_ext.php?oid=1",
        "https://vkvideo.ru/video_ext.php?oid=1",
        "https://ok.ru/videoembed/1",
        "https://video.sibnet.ru/shell.php?videoid=1",
        "https://sendvid.com/embed/abc",
        "https://anime-sama.to/x.mp4",
    ):
        assert _compat(_cmd(url)) == [], url


def test_le_drapeau_est_bien_porte_par_l_hote():
    assert get_extractor("https://myvi.tv/x").sans_certifi is True
    assert get_extractor("https://vk.com/x").sans_certifi is False


def test_no_certifi_ne_desactive_pas_la_verification():
    """La confusion a eviter : changer de magasin n'est pas cesser de verifier."""
    cmd = _cmd("https://www.myvi.tv/embed/abc")
    assert "--no-check-certificates" not in cmd
