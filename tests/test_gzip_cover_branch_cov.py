"""Regression: /api/anime/cover must be excluded from GZip. It serves a
FileResponse (accept-ranges: bytes); gzipping a 206/Range response corrupts the
body (Content-Range then describes uncompressed bytes). It joins the SSE and
video-stream paths in _NO_GZIP_PATHS, routed to the plain app.
"""

import asyncio

from web.api.app import _NO_GZIP_PATHS, COVER_PATH, GZipExceptSSE


def test_cover_path_in_no_gzip_set():
    assert COVER_PATH in _NO_GZIP_PATHS


def test_gzip_middleware_routes_cover_to_plain():
    called = {"plain": 0, "gzipped": 0}

    async def _plain(scope, receive, send):
        called["plain"] += 1

    async def _gzipped(scope, receive, send):
        called["gzipped"] += 1

    async def _inner(scope, receive, send):
        return None

    mw = GZipExceptSSE(_inner)
    mw.plain = _plain
    mw.gzipped = _gzipped

    async def _noop(*a):
        return None

    asyncio.run(mw({"type": "http", "path": COVER_PATH}, _noop, _noop))
    assert called == {"plain": 1, "gzipped": 0}

    asyncio.run(mw({"type": "http", "path": "/api/anime/episodes"}, _noop, _noop))
    assert called == {"plain": 1, "gzipped": 1}
