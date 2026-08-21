from engine.download.extractor.registry import get_extractor


def test_brand_fallback_attrape_tld_drift():
    assert get_extractor("https://uqload.foo/embed-x.html").name == "uqload"
    assert get_extractor("https://strm3.vidmoly.zzz/x").name == "vidmoly"


def test_brand_fallback_ne_matche_pas_domaine_attaquant():
    assert get_extractor("https://uqload.attacker.com/").name == "generic"
    assert get_extractor("https://vidmoly.evil.net/").name == "generic"


def test_brand_courte_exclue_pas_de_faux_positif():
    assert get_extractor("https://foo.ok.com/").name == "generic"
    assert get_extractor("https://bar.vk.io/").name == "generic"


def test_hote_inconnu_reste_generique():
    assert get_extractor("https://weird.unknown.tld/").name == "generic"
    assert get_extractor("https://player.example/embed").name == "generic"
