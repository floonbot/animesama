import asyncio

import pytest

import engine.scraping.search as search_mod
from engine.domain.exceptions import UnsafeUrlError
from engine.services.download_service import DownloadService


class FakeResp:

    def __init__(self, text="", ok=True):
        self.text = text
        self._ok = ok

    def __bool__(self):
        return self._ok


class FakeQueue:

    def __init__(self):
        self.ajoutes = []
        self.position = 7
        self._statut = {"en_cours": None, "queue": [], "historique": ["h1"]}
        self.annuler_ret = True
        self.pause_ret = True
        self.reprendre_ret = True

    async def ajouter(self, item):
        self.ajoutes.append(item)
        return self.position

    def statut(self):
        return self._statut

    def annuler(self):
        return self.annuler_ret

    def pause(self):
        return self.pause_ret

    def reprendre(self):
        return self.reprendre_ret


def make_service():
    svc = DownloadService()
    fake = FakeQueue()
    svc._queue = fake
    return svc, fake


@pytest.fixture(autouse=True)
def _restore_search_globals():
    saved_cache = dict(search_mod._types_cache)
    saved_loaded = search_mod._types_loaded
    try:
        yield
    finally:
        search_mod._types_cache.clear()
        search_mod._types_cache.update(saved_cache)
        search_mod._types_loaded = saved_loaded


def test_ajouter_episode_sanitizes_and_enqueues():
    svc, fake = make_service()
    item = {"ep": {"titre": "Naruto/Shippuden", "saison": 1, "episode": 5}}
    res = asyncio.run(svc.ajouter_episode(item))
    assert res["ok"] is True
    assert res["position"] == fake.position
    assert res["statut"] == fake._statut
    assert fake.ajoutes[0]["ep"]["titre"] == "Naruto_Shippuden"


def test_ajouter_episode_empty_ep_loses_titre_pinned():
    svc, fake = make_service()
    res = asyncio.run(svc.ajouter_episode({"ep": {}}))
    assert res["ok"] is True
    assert "titre" not in fake.ajoutes[0]["ep"]


def test_ajouter_episode_handles_missing_ep_key():
    svc, fake = make_service()
    res = asyncio.run(svc.ajouter_episode({}))
    assert res["ok"] is True
    assert len(fake.ajoutes) == 1
    assert "ep" not in fake.ajoutes[0]


def test_ajouter_direct_rejects_unsafe_url(monkeypatch):
    svc, fake = make_service()

    def _raise(_url):
        raise UnsafeUrlError("bloqué")

    monkeypatch.setattr(
        "engine.services.download_service.validate_external_url", _raise
    )
    res = asyncio.run(svc.ajouter_direct("http://127.0.0.1/x", "Nom"))
    assert res["ok"] is False
    assert "bloqué" in res["message"]
    assert fake.ajoutes == []


def test_ajouter_direct_success_sanitizes_and_filters_headers(monkeypatch):
    svc, fake = make_service()
    monkeypatch.setattr(
        "engine.services.download_service.validate_external_url",
        lambda url: url + "#ok",
    )
    headers = {
        "X-Good": "value",
        "X-Bad-CRLF": "line1\r\nline2",
        "X-Big": "z" * 1001,
        b"bytes-key": "v",
        "X-NonStr": 123,
    }
    res = asyncio.run(
        svc.ajouter_direct("https://host/stream.m3u8", "My/Name", headers)
    )
    assert res["ok"] is True
    assert res["nom"] == "My_Name"
    item = fake.ajoutes[0]
    assert item["_direct"] is True
    assert item["url_stream"] == "https://host/stream.m3u8#ok"
    assert item["nom"] == "My_Name"
    assert item["headers_stream"] == {"X-Good": "value"}


def test_ajouter_direct_default_nom(monkeypatch):
    svc, fake = make_service()
    monkeypatch.setattr(
        "engine.services.download_service.validate_external_url",
        lambda url: url,
    )
    res = asyncio.run(svc.ajouter_direct("https://host/a", "", None))
    assert res["nom"] == "Episode"
    assert fake.ajoutes[0]["headers_stream"] == {}


def test_sanitize_headers_non_dict_returns_empty():
    assert DownloadService._sanitize_headers(None) == {}
    assert DownloadService._sanitize_headers(["x"]) == {}


def test_sanitize_headers_drops_oversize_key():
    out = DownloadService._sanitize_headers({"k" * 101: "v", "ok": "v"})
    assert out == {"ok": "v"}


def test_sanitize_headers_drops_nul_byte():
    out = DownloadService._sanitize_headers({"a\x00b": "v", "ok": "v"})
    assert out == {"ok": "v"}


def test_ajouter_scan_invalid_slug(monkeypatch):
    svc, fake = make_service()
    monkeypatch.setattr("engine.scraping.scan.slug_valide", lambda s: False)
    res = asyncio.run(svc.ajouter_scan("BAD SLUG", "Oeuvre", "vf", ["1"]))
    assert res["ok"] is False
    assert res["message"] == "Slug invalide"
    assert fake.ajoutes == []


def test_ajouter_scan_empty_oeuvre(monkeypatch):
    svc, fake = make_service()
    monkeypatch.setattr("engine.scraping.scan.slug_valide", lambda s: True)
    res = asyncio.run(svc.ajouter_scan("slug", "   ", "vf", ["1"]))
    assert res["ok"] is False
    assert res["message"] == "Œuvre manquante"
    assert fake.ajoutes == []


def test_ajouter_scan_empty_chapitres(monkeypatch):
    svc, fake = make_service()
    monkeypatch.setattr("engine.scraping.scan.slug_valide", lambda s: True)
    res = asyncio.run(svc.ajouter_scan("slug", "Oeuvre", "vf", ["", "  "]))
    assert res["ok"] is False
    assert res["message"] == "Aucun chapitre sélectionné"
    assert fake.ajoutes == []


def test_ajouter_scan_happy_strips_filters_normalises(monkeypatch):
    svc, fake = make_service()
    monkeypatch.setattr("engine.scraping.scan.slug_valide", lambda s: True)
    monkeypatch.setattr(
        "engine.scraping.scan.normaliser_lang", lambda lang: "NORM"
    )
    res = asyncio.run(
        svc.ajouter_scan(
            "slug", "  Oeuvre  ", "weird", [" 1 ", "", 2, "  "], nom="N/ame"
        )
    )
    assert res["ok"] is True
    assert res["position"] == fake.position
    assert res["total"] == 2
    assert res["nom"] == "N_ame"
    item = fake.ajoutes[0]
    assert item["_scan"] is True
    assert item["oeuvre"] == "Oeuvre"
    assert item["chapitres"] == ["1", "2"]
    assert item["lang"] == "NORM"
    assert item["nom"] == "N_ame"


def test_ajouter_scan_caps_at_5000(monkeypatch):
    svc, fake = make_service()
    monkeypatch.setattr("engine.scraping.scan.slug_valide", lambda s: True)
    monkeypatch.setattr("engine.scraping.scan.normaliser_lang", lambda lang: "vf")
    chapitres = [str(i) for i in range(6000)]
    res = asyncio.run(svc.ajouter_scan("slug", "Oeuvre", "vf", chapitres))
    assert res["total"] == 5000
    assert len(fake.ajoutes[0]["chapitres"]) == 5000


def test_ajouter_scan_default_nom_from_oeuvre(monkeypatch):
    svc, fake = make_service()
    monkeypatch.setattr("engine.scraping.scan.slug_valide", lambda s: True)
    monkeypatch.setattr("engine.scraping.scan.normaliser_lang", lambda lang: "vf")
    res = asyncio.run(svc.ajouter_scan("slug", "MyOeuvre", "vf", ["1"]))
    assert res["nom"] == "MyOeuvre"


def test_annuler_delegates():
    svc, fake = make_service()
    fake.annuler_ret = False
    res = svc.annuler()
    assert res["ok"] is False
    assert res["statut"] == fake._statut


def test_pause_reprendre_delegate():
    svc, fake = make_service()
    assert svc.pause() == {"ok": True}
    assert svc.reprendre() == {"ok": True}
    fake.pause_ret = False
    assert svc.pause() == {"ok": False}


def test_statut_delegates():
    svc, fake = make_service()
    assert svc.statut() is fake._statut


def test_historique_extracts_from_statut():
    svc, fake = make_service()
    assert svc.historique() == ["h1"]


def test_historique_empty_when_missing_key():
    svc, fake = make_service()
    fake._statut = {"en_cours": None}
    assert svc.historique() == []


def _fake_auth(monkeypatch, cookies=None):
    import engine.auth.manager as auth_mod

    resolved = cookies if cookies is not None else []

    class _AM:
        pass

    am = _AM()
    am.cookies = resolved
    monkeypatch.setattr(auth_mod, "auth_manager", am)


def test_search_async_empty_query_returns_empty(monkeypatch):
    called = []
    monkeypatch.setattr(search_mod, "http_post", lambda *a, **k: called.append(a))
    assert asyncio.run(search_mod.search_async("")) == []
    assert asyncio.run(search_mod.search_async("   ")) == []
    assert called == []


def test_search_async_no_response_returns_empty(monkeypatch):
    _fake_auth(monkeypatch)

    async def _post(url, cookies, data):
        return FakeResp(ok=False)

    monkeypatch.setattr(search_mod, "http_post", _post)
    monkeypatch.setattr(
        "engine.scraping.parser.parse_search_results",
        lambda html: (_ for _ in ()).throw(AssertionError("should not parse")),
    )
    assert asyncio.run(search_mod.search_async("naruto")) == []


def test_search_async_parses_results(monkeypatch):
    _fake_auth(monkeypatch, cookies=[{"name": "c", "value": "v"}])
    seen = []

    async def _post(url, cookies, data):
        seen.append((url, dict(data)))
        assert cookies == [{"name": "c", "value": "v"}]
        return FakeResp(text="<html>payload</html>")

    parsed = [{"nom": "Naruto", "image": "img.png"}]
    monkeypatch.setattr(search_mod, "http_post", _post)
    monkeypatch.setattr(
        "engine.scraping.parser.parse_search_results",
        lambda html: parsed if html == "<html>payload</html>" else [],
    )
    res = asyncio.run(search_mod.search_async("naruto"))
    assert res == parsed
    assert seen and seen[0][0] == search_mod.SEARCH_URL
    assert seen[0][1] == {"query": "naruto"}


def test_search_async_fills_known_covers(monkeypatch):
    _fake_auth(monkeypatch)

    async def _post(url, cookies, data):
        return FakeResp(text="x")

    monkeypatch.setattr(search_mod, "http_post", _post)
    monkeypatch.setattr(
        "engine.scraping.parser.parse_search_results",
        lambda html: [
            {"nom": "A", "image": ""},
            {"nom": "B", "image": "keep.png"},
        ],
    )
    res = asyncio.run(
        search_mod.search_async("q", known_covers={"A": "cover-a.png"})
    )
    assert res[0]["image"] == "cover-a.png"
    assert res[1]["image"] == "keep.png"


def test_search_async_truncates_long_query(monkeypatch):
    _fake_auth(monkeypatch)
    seen = []

    async def _post(url, cookies, data):
        seen.append(dict(data))
        return FakeResp(text="x")

    monkeypatch.setattr(search_mod, "http_post", _post)
    monkeypatch.setattr(
        "engine.scraping.parser.parse_search_results", lambda html: []
    )
    long_q = "a" * (search_mod.SEARCH_MAX_LEN + 50)
    asyncio.run(search_mod.search_async(long_q))
    assert seen
    assert seen[0]["query"] == "a" * search_mod.SEARCH_MAX_LEN
    assert len(seen[0]["query"]) == search_mod.SEARCH_MAX_LEN


def test_search_async_exception_returns_empty(monkeypatch):
    _fake_auth(monkeypatch)

    async def _post(url, cookies, data):
        raise RuntimeError("network down")

    monkeypatch.setattr(search_mod, "http_post", _post)
    assert asyncio.run(search_mod.search_async("q")) == []


def test_detecter_types_empty_urls_returns_empty():
    assert asyncio.run(search_mod.detecter_types_favoris_async([])) == {}


def test_detecter_types_uses_cache_no_fetch(monkeypatch):
    monkeypatch.setattr(search_mod, "_types_loaded", True)
    search_mod._types_cache.clear()
    search_mod._types_cache["https://anime-sama.to/catalogue/x"] = "scan"

    async def _boom(*a, **k):
        raise AssertionError("http_get should not be called when cached")

    monkeypatch.setattr(search_mod, "http_get", _boom)
    res = asyncio.run(
        search_mod.detecter_types_favoris_async(
            ["https://anime-sama.to/catalogue/x"]
        )
    )
    assert res == {"https://anime-sama.to/catalogue/x": "scan"}


def test_detecter_types_safe_url_gate_skips_unsafe(monkeypatch):
    monkeypatch.setattr(search_mod, "_types_loaded", True)
    search_mod._types_cache.clear()
    monkeypatch.setattr(search_mod, "_is_safe_url", lambda u: False)

    async def _boom(*a, **k):
        raise AssertionError("unsafe url must not be fetched")

    monkeypatch.setattr(search_mod, "http_get", _boom)
    res = asyncio.run(
        search_mod.detecter_types_favoris_async(["http://evil.example/x"])
    )
    assert res == {}


def test_detecter_types_fetch_and_classify(monkeypatch):
    _fake_auth(monkeypatch)
    monkeypatch.setattr(search_mod, "_types_loaded", True)
    search_mod._types_cache.clear()
    monkeypatch.setattr(search_mod, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(search_mod, "_save_types_cache", lambda: None)

    url = "https://anime-sama.to/catalogue/foo"

    async def _get(u, cookies):
        return FakeResp(text="page")

    monkeypatch.setattr(search_mod, "http_get", _get)
    monkeypatch.setattr(
        "engine.scraping.parser.detecter_type_contenu",
        lambda html: {"has_scan": True, "has_anime": True},
    )
    res = asyncio.run(search_mod.detecter_types_favoris_async([url]))
    assert res == {url: "both"}
    assert search_mod._types_cache[url] == "both"
