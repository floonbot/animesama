import pytest
from fastapi.testclient import TestClient

_VIDEO_SIZE = 200_000


@pytest.fixture
def stream_client(tmp_path, monkeypatch):
    from engine.library import scanner

    monkeypatch.setattr(scanner, "dossiers_actifs", lambda: [tmp_path])
    from web.api.app import create_app

    fichier = tmp_path / "ep.mp4"
    fichier.write_bytes(b"\x00" * _VIDEO_SIZE)
    client = TestClient(create_app(), base_url="http://localhost")
    return client, str(fichier)


def test_stream_full_response_not_gzipped(stream_client):
    client, fichier = stream_client
    r = client.get(
        "/api/anime/stream",
        params={"fichier": fichier},
        headers={"Accept-Encoding": "gzip"},
    )
    assert r.status_code == 200
    assert r.headers.get("content-encoding") != "gzip"
    assert r.headers.get("accept-ranges") == "bytes"
    assert r.headers.get("content-length") == str(_VIDEO_SIZE)


def test_stream_range_returns_206_with_intact_content_length(stream_client):
    client, fichier = stream_client
    r = client.get(
        "/api/anime/stream",
        params={"fichier": fichier},
        headers={"Accept-Encoding": "gzip", "Range": "bytes=0-149999"},
    )
    assert r.status_code == 206
    assert r.headers.get("content-encoding") != "gzip"
    assert "content-range" in r.headers
    assert r.headers.get("content-length") == "150000"
    assert len(r.content) == 150000


def test_gzip_still_applies_to_non_stream_paths():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from web.api.app import STREAM_PATH, GZipExceptSSE

    big = "x" * 5000

    async def _big(request):
        return PlainTextResponse(big)

    app = Starlette(routes=[Route("/normal", _big), Route(STREAM_PATH, _big)])
    app.add_middleware(GZipExceptSSE, minimum_size=500)
    client = TestClient(app)

    normal = client.get("/normal", headers={"Accept-Encoding": "gzip"})
    assert normal.headers.get("content-encoding") == "gzip"

    stream = client.get(STREAM_PATH, headers={"Accept-Encoding": "gzip"})
    assert stream.headers.get("content-encoding") != "gzip"
