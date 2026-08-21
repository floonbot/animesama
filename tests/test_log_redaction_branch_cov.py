import asyncio

from engine.download import interceptor
from engine.download.extractor import browser_extractor
from engine.download.methods import nm3u8dl

_TOKEN = "AB12cd34EF56gh78IJ90klmn3456"


def test_nm3u8dl_invalid_url_redacts_path_token(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(nm3u8dl, "_get_nm3u8dl_path", lambda: "N_m3u8DL-RE")
    url = f"ftp://cdn.example/{_TOKEN}/x"
    with caplog.at_level("ERROR"):
        res = nm3u8dl.nm3u8dl_download(url, str(tmp_path), "ep")
    assert res is None
    assert "URL invalide refusée" in caplog.text
    assert _TOKEN not in caplog.text


def test_extraire_flux_invalid_url_redacts_path_token(caplog):
    url = f"ftp://cdn.example/{_TOKEN}/x"
    with caplog.at_level("WARNING"):
        res = asyncio.run(browser_extractor.extraire_flux(url))
    assert res == {"best": None, "all": [], "timeline": []}
    assert _TOKEN not in caplog.text


def test_intercepter_lecteur_invalid_url_redacts_path_token(caplog):
    url = f"ftp://cdn.example/{_TOKEN}/x"
    with caplog.at_level("WARNING"):
        res = asyncio.run(interceptor.intercepter_lecteur(url))
    assert res is None
    assert _TOKEN not in caplog.text
