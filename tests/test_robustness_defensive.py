from engine.download import interceptor
from engine.download._domain_strategy import partition_lecteurs


def test_partition_lecteurs_ignores_non_dict_entries():
    lecteurs = ["oops", None, 123, {"src": "https://host.example/v.mp4"}]
    ytdlp, autres = partition_lecteurs(lecteurs)
    kept = ytdlp + autres
    assert kept == [{"src": "https://host.example/v.mp4"}]


def test_meilleur_resultat_skips_entries_without_url():
    resultats = [{"type": "noise"}, {"url": "https://cdn/x.m3u8", "type": "hls"}]
    assert interceptor._meilleur_resultat(resultats) == {"url": "https://cdn/x.m3u8", "type": "hls"}


def test_meilleur_resultat_all_without_url_returns_first():
    resultats = [{"type": "a"}, {"type": "b"}]
    assert interceptor._meilleur_resultat(resultats) == {"type": "a"}


def test_meilleur_resultat_prefers_txt_when_no_m3u8():
    resultats = [{"url": "https://cdn/a.bin"}, {"url": "https://cdn/b.txt"}]
    assert interceptor._meilleur_resultat(resultats) == {"url": "https://cdn/b.txt"}
