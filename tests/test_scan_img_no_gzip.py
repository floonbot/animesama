import zipfile

import pytest
from fastapi.testclient import TestClient

import engine.library.scanner as scanner
from web.api.app import create_app

# JPEG minimal mais compressible : sans exclusion, gzip mordrait dessus.
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 4000 + b"\xff\xd9"


@pytest.fixture
def cbz(tmp_path, monkeypatch):
    chemin = tmp_path / "Chapitre 1.cbz"
    with zipfile.ZipFile(chemin, "w") as zf:
        zf.writestr("001.jpg", _JPEG)
    monkeypatch.setattr(scanner, "est_dans_downloads", lambda _f: True)
    return str(chemin)


@pytest.fixture
def c():
    return TestClient(create_app(), base_url="http://localhost")


def test_image_de_scan_non_gzippee(c, cbz):
    r = c.get(
        "/api/anime/scan-local-img",
        params={"fichier": cbz, "page": 0},
        headers={"Accept-Encoding": "gzip"},
    )

    assert r.status_code == 200, r.text
    assert r.headers.get("content-type") == "image/jpeg"
    assert r.headers.get("content-encoding") != "gzip"
    assert len(r.content) == len(_JPEG)


def test_une_route_json_reste_compressee(c):
    r = c.get("/api/metrics", headers={"Accept-Encoding": "gzip"})

    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"


def test_la_route_est_classee_media(c, cbz):
    from web.api.app import _NO_GZIP_PATHS

    assert "/api/anime/scan-local-img" in _NO_GZIP_PATHS
