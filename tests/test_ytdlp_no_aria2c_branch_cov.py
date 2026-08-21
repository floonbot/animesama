from engine.download.extractor.registry import get_extractor
from engine.download.methods._ytdlp_parsing import construire_commande


def test_sibnet_extractor_declares_no_aria2c():
    ext = get_extractor("https://video.sibnet.ru/shell.php?videoid=123")
    assert ext.name == "sibnet"
    assert ext.no_aria2c is True


def test_construire_commande_omet_aria2c_pour_sibnet():
    cmd = construire_commande(
        "yt", "https://dv97.sibnet.ru/47/82/72/4782728.mp4",
        "/d", "n", {}, "auto", aria2c="/bin/aria2c",
    )
    assert "aria2c" not in " ".join(cmd)
    assert "--downloader" not in cmd


def test_construire_commande_garde_aria2c_pour_hote_neutre():
    cmd = construire_commande(
        "yt", "https://cdn.example.tld/v.mp4",
        "/d", "n", {}, "auto", aria2c="/bin/aria2c",
    )
    assert "--downloader" in cmd
    i = cmd.index("--downloader")
    assert cmd[i + 1] == "aria2c"


def test_construire_commande_sans_aria2c_reste_sans_downloader():
    cmd = construire_commande("yt", "https://video.sibnet.ru/x", "/d", "n", {}, "auto")
    assert "--downloader" not in cmd
