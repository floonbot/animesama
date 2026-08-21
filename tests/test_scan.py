
import json
import zipfile

import pytest

from engine.download.methods import images as img_mod
from engine.scraping import scan as scan_mod

WRITE_HEADERS = {"origin": "http://localhost:7843"}

_PAGE_HTML = (
    '<html><body>'
    '<h3 id="titreOeuvre" class="x">99 reinforced wood stick</h3>'
    '<select id="selectChapitres"><option>Chapitre 1</option></select>'
    '</body></html>'
)

def test_slug_valide():
    assert scan_mod.slug_valide("99-reinforced-wood-stick")
    assert scan_mod.slug_valide("one_piece.2")
    assert not scan_mod.slug_valide("../etc/passwd")
    assert not scan_mod.slug_valide("a/b")
    assert not scan_mod.slug_valide("")
    assert not scan_mod.slug_valide("x" * 200)

def test_normaliser_lang():
    assert scan_mod.normaliser_lang("vf") == "vf"
    assert scan_mod.normaliser_lang("VA") == "va"
    assert scan_mod.normaliser_lang("vostfr") == "vf"
    assert scan_mod.normaliser_lang(None) == "vf"

def test_extraire_oeuvre():
    assert scan_mod._extraire_oeuvre(_PAGE_HTML) == "99 reinforced wood stick"
    assert scan_mod._extraire_oeuvre("<html>no title</html>") is None

def test_chap_sort_key_decimals():
    nums = ["10", "2", "1", "10.5", "3"]
    nums.sort(key=scan_mod._chap_sort_key)
    assert nums == ["1", "2", "3", "10", "10.5"]

def test_get_scan_info_sync(monkeypatch):
    def fake_fetch(url, referer=None, max_bytes=0):
        if "/scan/vf" in url:
            return 200, _PAGE_HTML
        if "/scan/va" in url:
            return 404, ""
        if "get_nb_chap_et_img" in url:
            return 200, json.dumps({"1": 20, "2": 18, "10": 12, "3": 9})
        return -1, ""

    monkeypatch.setattr(scan_mod, "_fetch_text", fake_fetch)
    info = scan_mod.get_scan_info_sync("99-reinforced-wood-stick", "vf")
    assert info["ok"] is True
    assert info["oeuvre"] == "99 reinforced wood stick"
    assert info["lang"] == "vf"
    assert info["langues"] == ["vf"]
    assert [c["num"] for c in info["chapitres"]] == ["1", "2", "3", "10"]
    assert info["chapitres"][0]["pages"] == 20
    assert info["total"] == 4

def test_get_scan_info_sync_no_scan(monkeypatch):
    monkeypatch.setattr(scan_mod, "_fetch_text", lambda *a, **k: (404, ""))
    info = scan_mod.get_scan_info_sync("inexistant", "vf")
    assert info["ok"] is False
    assert info["chapitres"] == []

def test_get_scan_info_sync_bad_slug(monkeypatch):
    info = scan_mod.get_scan_info_sync("../evil", "vf")
    assert info["ok"] is False

def test_get_pages_sync(monkeypatch):
    def fake_fetch(url, referer=None, max_bytes=0):
        if "get_nb_chap_et_img" in url:
            return 200, json.dumps({"1": 3, "2": 5})
        return 404, ""

    monkeypatch.setattr(scan_mod, "_fetch_text", fake_fetch)
    out = scan_mod.get_pages_sync("Mon Oeuvre", "1", "vf")
    assert [p["page"] for p in out] == [1, 2, 3]
    assert out[0]["url"].endswith("/s2/scans/Mon%20Oeuvre/1/1.jpg")
    assert out[-1]["url"].endswith("/s2/scans/Mon%20Oeuvre/1/3.jpg")
    assert scan_mod.get_pages_sync("Mon Oeuvre", "99", "vf") == []

def test_ext_depuis():
    assert img_mod._ext_depuis("x", "image/png") == ".png"
    assert img_mod._ext_depuis("x", "image/jpeg; charset=binary") == ".jpg"
    assert img_mod._ext_depuis("https://h/a/1.webp", "") == ".webp"
    assert img_mod._ext_depuis("https://h/a/1.jpeg", "") == ".jpg"
    assert img_mod._ext_depuis("https://h/a/1", "application/octet-stream") == ".jpg"

class _Tok:
    def __init__(self, val):
        self.val = val

    def is_cancelled(self):
        return self.val

def test_est_annule():
    assert img_mod._est_annule(None) is False
    assert img_mod._est_annule(_Tok(True)) is True
    assert img_mod._est_annule(_Tok(False)) is False

def test_scan_download_builds_cbz(monkeypatch, tmp_path):
    pages = {
        "1": [{"page": 1, "url": "u1"}, {"page": 2, "url": "u2"}],
    }
    monkeypatch.setattr(scan_mod, "get_pages_sync", lambda oeuvre, chap, lang: pages.get(str(chap), []))
    monkeypatch.setattr(img_mod, "_telecharger_image", lambda session, url, *a: (b"\xff\xd8fakejpg", ".jpg"))

    progress = []
    out = img_mod.scan_download(
        "X", "vf", ["1"], str(tmp_path),
        cancelled=None, on_progress=lambda pct, line: progress.append((pct, line)),
    )
    cbz = tmp_path / "Chapitre 1.cbz"
    assert out == str(cbz)
    assert cbz.exists()
    with zipfile.ZipFile(cbz) as zf:
        assert zf.namelist() == ["001.jpg", "002.jpg"]
    assert progress

def test_scan_download_skips_existing(monkeypatch, tmp_path):
    (tmp_path / "Chapitre 1.cbz").write_bytes(b"already")

    def _boom(*a, **k):
        raise AssertionError("get_pages_sync ne devrait pas être appelé")

    monkeypatch.setattr(scan_mod, "get_pages_sync", _boom)
    out = img_mod.scan_download("X", "vf", ["1"], str(tmp_path))
    assert out == str(tmp_path / "Chapitre 1.cbz")

def test_scan_download_cancellation(monkeypatch, tmp_path):
    from engine.domain.exceptions import DownloadCancelled
    monkeypatch.setattr(scan_mod, "get_pages_sync", lambda *a, **k: [{"page": 1, "url": "u"}])
    with pytest.raises(DownloadCancelled):
        img_mod.scan_download("X", "vf", ["1"], str(tmp_path), cancelled=_Tok(True))
    assert list(tmp_path.glob("*.part")) == []

def test_route_scan_info(client, monkeypatch):
    async def _fake(slug, lang):
        return {"ok": True, "slug": slug, "oeuvre": "X", "lang": lang,
                "langues": ["vf"], "chapitres": [{"num": "1", "pages": 20}], "total": 1}
    monkeypatch.setattr(scan_mod, "get_scan_info", _fake)
    r = client.get("/api/anime/scan", params={"slug": "99-reinforced-wood-stick", "lang": "vf"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["total"] == 1

def test_route_scan_info_bad_slug(client):
    r = client.get("/api/anime/scan", params={"slug": "../evil", "lang": "vf"})
    assert r.status_code == 400

def test_route_dl_scan(client, monkeypatch):
    from engine.services.download_service import download_service

    async def _fake_add(slug, oeuvre, lang, chapitres, nom):
        return {"ok": True, "position": 1, "nom": nom, "total": len(chapitres)}

    monkeypatch.setattr(download_service, "ajouter_scan", _fake_add)
    r = client.post("/api/download/scan", headers=WRITE_HEADERS,
                    json={"slug": "x", "oeuvre": "X", "lang": "vf", "chapitres": ["1", "2"], "nom": "X"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["total"] == 2

def test_route_dl_scan_empty(client):
    r = client.post("/api/download/scan", headers=WRITE_HEADERS,
                    json={"slug": "x", "oeuvre": "X", "lang": "vf", "chapitres": []})
    assert r.status_code == 200
    assert r.json()["ok"] is False

def test_route_scan_pages(client, monkeypatch):
    async def _fake(oeuvre, chap, lang):
        return [{"page": 1, "url": "https://anime-sama.to/a/1.jpg"}]
    monkeypatch.setattr(scan_mod, "get_pages", _fake)
    r = client.get("/api/anime/scan-pages", params={"oeuvre": "X", "chap": "1", "lang": "vf"})
    assert r.status_code == 200
    assert len(r.json()["pages"]) == 1

def _make_cbz(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("001.jpg", b"\xff\xd8aaa")
        zf.writestr("002.jpg", b"\xff\xd8bbb")
        zf.writestr("notes.txt", b"ignored")

def test_route_scan_local(client, monkeypatch, tmp_path):
    import engine.library.scanner as scanner_mod
    cbz = tmp_path / "Chapitre 1.cbz"
    _make_cbz(cbz)
    monkeypatch.setattr(scanner_mod, "est_dans_downloads", lambda f: True)

    r = client.get("/api/anime/scan-local", params={"fichier": str(cbz)})
    assert r.status_code == 200 and r.json()["pages"] == 2

    r2 = client.get("/api/anime/scan-local-img", params={"fichier": str(cbz), "page": 0})
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("image/")
    assert r2.content.startswith(b"\xff\xd8")

    r3 = client.get("/api/anime/scan-local-img", params={"fichier": str(cbz), "page": 9})
    assert r3.status_code == 404

def test_route_scan_local_rejects_non_cbz(client):
    r = client.get("/api/anime/scan-local", params={"fichier": "/x/y.mp4"})
    assert r.status_code == 400

def test_route_scan_local_rejects_outside(client, monkeypatch, tmp_path):
    import engine.library.scanner as scanner_mod
    cbz = tmp_path / "Chapitre 1.cbz"
    _make_cbz(cbz)
    monkeypatch.setattr(scanner_mod, "est_dans_downloads", lambda f: False)
    r = client.get("/api/anime/scan-local", params={"fichier": str(cbz)})
    assert r.status_code == 403

def test_scanner_indexes_cbz(tmp_path):
    from engine.library import scanner
    saison = tmp_path / "Mon Manga" / "Scan VF"
    saison.mkdir(parents=True)
    _make_cbz(saison / "Chapitre 1.cbz")
    animes, _ = scanner._scan_un_dossier(tmp_path)
    assert "Mon Manga" in animes
    eps = animes["Mon Manga"]["saisons"][0]["episodes"]
    assert eps[0]["scan"] is True
    assert eps[0]["nom"] == "Chapitre 1"

def test_library_merges_anime_and_scan(monkeypatch, tmp_path):
    import engine.library.scanner as scanner
    dl = tmp_path / "dl"
    sc = tmp_path / "sc"
    (dl / "Dungeon Defense" / "Saison 1").mkdir(parents=True)
    (dl / "Dungeon Defense" / "Saison 1" / "S01E01.mp4").write_bytes(b"x" * 10)
    (sc / "dungeon-defense" / "Scan VF").mkdir(parents=True)
    _make_cbz(sc / "dungeon-defense" / "Scan VF" / "Chapitre 1.cbz")

    monkeypatch.setattr(scanner, "dossiers_actifs", lambda: [dl, sc])
    scanner.invalider_cache_librairie()
    res = scanner.scan_librairie_sync()
    scanner.invalider_cache_librairie()

    assert len(res["animes"]) == 1
    a = res["animes"][0]
    saisons = {s["nom"] for s in a["saisons"]}
    assert "Saison 1" in saisons and "Scan VF" in saisons
    eps = [e for s in a["saisons"] for e in s["episodes"]]
    assert any(e.get("scan") for e in eps)
    assert any(not e.get("scan") for e in eps)

def test_scan_types_cache_disk_roundtrip(monkeypatch, tmp_path):
    import engine.scraping.search as search
    f = tmp_path / "scan_types.json"
    monkeypatch.setattr(search, "_TYPES_FILE", f)
    monkeypatch.setattr(search, "_types_loaded", False)
    with search._types_cache_lock:
        search._types_cache.clear()
        search._types_cache["https://x/a"] = "scan"
        search._types_cache["https://x/b"] = "anime"
    search._save_types_cache()
    assert f.exists()
    with search._types_cache_lock:
        search._types_cache.clear()
    monkeypatch.setattr(search, "_types_loaded", False)
    search._load_types_cache()
    assert search._types_cache.get("https://x/a") == "scan"
    assert search._types_cache.get("https://x/b") == "anime"
    with search._types_cache_lock:
        search._types_cache.clear()

def test_scans_dir_configured():
    import engine.config.settings as cfg
    sd = cfg.get_scans_dir()
    assert sd.is_absolute()
    assert sd == cfg.SCANS_DIR or (sd.exists() and sd.is_dir())

def test_library_includes_scans_dir(monkeypatch, tmp_path):
    import engine.config.settings as cfg
    import engine.library.scanner as scanner
    dl = tmp_path / "dl"
    sc = tmp_path / "sc"
    dl.mkdir()
    sc.mkdir()
    monkeypatch.setattr(cfg, "get_downloads_dir", lambda: dl)
    monkeypatch.setattr(cfg, "get_scans_dir", lambda: sc)
    scanner.invalider_cache_dossiers()
    try:
        resolved = {str(p.resolve()).lower() for p in scanner.dossiers_actifs()}
        assert str(dl.resolve()).lower() in resolved
        assert str(sc.resolve()).lower() in resolved
    finally:
        scanner.invalider_cache_dossiers()
