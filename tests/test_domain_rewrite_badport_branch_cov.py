from engine.config.settings import HOST_DOMAIN_REWRITES
from engine.download._domain_strategy import reecrire_domaine


def test_reecrire_domaine_out_of_range_port_no_crash():
    assert "vidmoly.to" in HOST_DOMAIN_REWRITES
    assert (
        reecrire_domaine("https://vidmoly.to:99999/embed-x.html")
        == "https://vidmoly.to:99999/embed-x.html"
    )


def test_reecrire_domaine_non_numeric_port_no_crash():
    assert (
        reecrire_domaine("https://vidmoly.to:abc/embed-x.html")
        == "https://vidmoly.to:abc/embed-x.html"
    )
