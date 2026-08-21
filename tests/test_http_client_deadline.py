import asyncio

import engine.scraping.http_client as hc


class _AdvancingClock:
    def __init__(self, step):
        self.t = 0.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


class _NeverEndingResp:
    def __init__(self, max_chunks=1000):
        self.headers: dict = {}
        self.consumed = 0
        self._max = max_chunks
        self.encoding = None
        self._content = None
        self._content_consumed = False

    def iter_content(self, size):
        for _ in range(self._max):
            self.consumed += 1
            yield b"x" * 1024

    def close(self):
        pass


def test_lire_corps_borne_aborts_on_wallclock_deadline(monkeypatch):
    monkeypatch.setattr(hc, "HTTP_BODY_DEADLINE", 6)
    monkeypatch.setattr(hc.time, "monotonic", _AdvancingClock(step=2.0))
    r = _NeverEndingResp()

    out = hc._lire_corps_borne(r, "http://x/big")

    assert out is None
    assert r.consumed < 1000


def test_lire_corps_borne_returns_body_under_deadline(monkeypatch):
    monkeypatch.setattr(hc, "HTTP_BODY_DEADLINE", 1000)
    monkeypatch.setattr(hc.time, "monotonic", _AdvancingClock(step=0.001))
    r = _NeverEndingResp(max_chunks=4)

    out = hc._lire_corps_borne(r, "http://x/small")

    assert out == b"x" * 1024 * 4


class _NeverEndingAsyncResp:
    def __init__(self):
        self.headers: dict = {}
        self.is_success = True
        self.status_code = 200
        self.consumed = 0

    async def aiter_bytes(self, size):
        for _ in range(1000):
            self.consumed += 1
            yield b"x" * 1024


class _AsyncStreamCM:
    def __init__(self, resp):
        self._r = resp

    async def __aenter__(self):
        return self._r

    async def __aexit__(self, *exc):
        return False


class _FakeAsyncClient:
    def __init__(self, resp):
        self._r = resp

    def stream(self, method, url, **kwargs):
        return _AsyncStreamCM(self._r)


def test_http_get_async_aborts_on_wallclock_deadline(monkeypatch):
    resp = _NeverEndingAsyncResp()

    async def _fake_client():
        return _FakeAsyncClient(resp)

    monkeypatch.setattr(hc, "_get_async_client", _fake_client)
    monkeypatch.setattr(hc, "HTTP_BODY_DEADLINE", 6)
    monkeypatch.setattr(hc.time, "monotonic", _AdvancingClock(step=2.0))

    out = asyncio.run(hc._http_get_async("http://x/big", None))

    assert out is None
    assert resp.consumed < 1000
