import asyncio
import ssl
import sys
import types

import httpx
import pytest

import engine.scraping.http_client as hc


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch):
    saved_cache = dict(hc._session_cache)
    saved_order = list(hc._session_keys_order)
    saved_async = dict(hc._async_client_state)
    monkeypatch.setattr(hc.time, "sleep", lambda *a, **k: None)
    hc._async_client_state["client"] = None
    hc._async_client_state["loop"] = None
    FakeAsyncClient.instances.clear()
    yield
    FakeAsyncClient.instances.clear()
    hc._session_cache.clear()
    hc._session_cache.update(saved_cache)
    hc._session_keys_order[:] = saved_order
    hc._async_client_state.clear()
    hc._async_client_state.update(saved_async)


class _FakeCookieJar:
    def __init__(self):
        self.set_calls = []
        self.cleared = 0

    def set(self, name, value, **kwargs):
        self.set_calls.append((name, value, kwargs))

    def clear(self):
        self.cleared += 1


class _RaisingCookieJar:
    def clear(self):
        raise RuntimeError("cannot clear")


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.cookies = _FakeCookieJar()
        self.mounted = {}

    def mount(self, prefix, adapter):
        self.mounted[prefix] = adapter


class FakeAsyncResponse:
    def __init__(self, status_code=200, is_success=None, headers=None, chunks=(b"hi",)):
        self.status_code = status_code
        self.is_success = (status_code == 200) if is_success is None else is_success
        self.headers = dict(headers or {})
        self._chunks = list(chunks)

    async def aiter_bytes(self, size):
        for c in self._chunks:
            yield c


class _AsyncStreamCtx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


class FakeAsyncClient:
    instances = []

    def __init__(self, scripted=(), **kwargs):
        self._scripted = list(scripted)
        self.kwargs = kwargs
        self.stream_calls = []
        self.aclose_count = 0
        self.cookies = _FakeCookieJar()
        FakeAsyncClient.instances.append(self)

    def stream(self, method, url, **kwargs):
        self.stream_calls.append((method, url, kwargs))
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return _AsyncStreamCtx(item)

    async def aclose(self):
        self.aclose_count += 1


def _run(coro):
    return asyncio.run(coro)


def _install_fake_httpx(monkeypatch, async_client_factory):
    mod = types.ModuleType("httpx")
    mod.AsyncClient = async_client_factory
    mod.Limits = lambda **kwargs: ("limits", kwargs)
    mod.TimeoutException = httpx.TimeoutException
    mod.ConnectError = httpx.ConnectError
    mod.HTTPError = httpx.HTTPError
    monkeypatch.setitem(sys.modules, "httpx", mod)
    return mod


def test_build_session_swallows_httpadapter_import_failure(monkeypatch):
    fake = FakeSession()
    monkeypatch.setattr(hc.req, "Session", lambda: fake)
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "requests.adapters":
            raise ImportError("no adapters")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    s = hc._build_session([{"name": "tok", "value": "v"}])
    assert s is fake
    assert s.mounted == {}
    assert s.cookies.set_calls == [("tok", "v", {"domain": "", "path": "/"})]
    assert s.headers["User-Agent"] == hc.USER_AGENT


def test_build_session_mounts_adapter_on_both_schemes(monkeypatch):
    fake = FakeSession()
    monkeypatch.setattr(hc.req, "Session", lambda: fake)
    s = hc._build_session([])
    assert set(s.mounted) == {"https://", "http://"}
    assert s.mounted["https://"] is s.mounted["http://"]


def test_build_session_skips_cookie_without_value(monkeypatch):
    fake = FakeSession()
    monkeypatch.setattr(hc.req, "Session", lambda: fake)
    cookies = [
        {"name": "keep", "value": "y", "domain": "ex", "path": "/a"},
        {"name": "novalue"},
        {"name": "emptyval", "value": ""},
        "notadict",
    ]
    hc._build_session(cookies)
    assert fake.cookies.set_calls == [("keep", "y", {"domain": "ex", "path": "/a"})]


def test_clear_session_cache_swallows_cookie_clear_exception():
    class _Client:
        cookies = _RaisingCookieJar()

    hc._async_client_state["client"] = _Client()
    hc.clear_session_cache()
    assert hc._async_client_state["client"] is not None


def test_clear_session_cache_no_async_client_does_not_raise():
    hc._async_client_state["client"] = None
    hc.clear_session_cache()
    assert hc._session_cache == {}


def test_get_async_client_returns_none_when_httpx_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "httpx", None)
    out = _run(hc._get_async_client())
    assert out is None
    assert hc._async_client_state["client"] is None


def test_get_async_client_creates_and_caches_for_same_loop(monkeypatch):
    FakeAsyncClient.instances.clear()
    _install_fake_httpx(monkeypatch, FakeAsyncClient)

    async def main():
        first = await hc._get_async_client()
        second = await hc._get_async_client()
        return first, second, asyncio.get_running_loop()

    first, second, loop = _run(main())
    assert first is second
    assert len(FakeAsyncClient.instances) == 1
    assert hc._async_client_state["client"] is first
    assert hc._async_client_state["loop"] is loop
    assert first.kwargs["timeout"] == hc.HTTP_TIMEOUT
    assert first.kwargs["headers"]["User-Agent"] == hc.USER_AGENT
    assert first.kwargs["follow_redirects"] is True


def test_get_async_client_recreates_on_loop_change_and_closes_old(monkeypatch):
    FakeAsyncClient.instances.clear()
    _install_fake_httpx(monkeypatch, FakeAsyncClient)

    async def make():
        return await hc._get_async_client()

    old = _run(make())
    assert old.aclose_count == 0
    new = _run(make())
    assert new is not old
    assert len(FakeAsyncClient.instances) == 2
    assert old.aclose_count == 1
    assert hc._async_client_state["client"] is new


def test_get_async_client_swallows_old_aclose_error(monkeypatch):
    class BoomCloseClient(FakeAsyncClient):
        async def aclose(self):
            self.aclose_count += 1
            raise RuntimeError("close failed")

    FakeAsyncClient.instances.clear()
    _install_fake_httpx(monkeypatch, BoomCloseClient)

    async def make():
        return await hc._get_async_client()

    old = _run(make())
    new = _run(make())
    assert old.aclose_count == 1
    assert new is not old
    assert hc._async_client_state["client"] is new


def _patch_get_client(monkeypatch, client):
    async def fake_get_client():
        return client

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)


def test_http_get_async_410_permanent(monkeypatch):
    resp = FakeAsyncResponse(status_code=410, is_success=False)
    client = FakeAsyncClient([resp])
    _patch_get_client(monkeypatch, client)
    out = _run(hc._http_get_async("https://anime-sama.to/gone", None))
    assert out is None
    assert len(client.stream_calls) == 1


def test_http_get_async_connecterror_with_ssl_cause_returns_none(monkeypatch):
    async def fake_sleep(s):
        raise AssertionError("must not sleep on SSL connect error")

    monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
    err = httpx.ConnectError("ssl handshake")
    err.__cause__ = ssl.SSLError("bad cert")
    client = FakeAsyncClient([err])
    _patch_get_client(monkeypatch, client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out is None
    assert len(client.stream_calls) == 1


def test_http_get_async_connecterror_without_ssl_retried_then_none(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
    errs = [httpx.ConnectError("refused") for _ in range(hc.HTTP_RETRIES + 1)]
    client = FakeAsyncClient(errs)
    _patch_get_client(monkeypatch, client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out is None
    assert len(client.stream_calls) == hc.HTTP_RETRIES + 1
    assert sleeps == [hc.RETRY_DELAY] * hc.HTTP_RETRIES


def test_http_get_async_connecterror_then_success(monkeypatch):
    async def fake_sleep(s):
        return None

    monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
    ok = FakeAsyncResponse(status_code=200, chunks=[b"recovered"])
    client = FakeAsyncClient([httpx.ConnectError("refused"), ok])
    _patch_get_client(monkeypatch, client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert isinstance(out, hc._AsyncResp)
    assert out.text == "recovered"
    assert len(client.stream_calls) == 2


def test_http_get_async_httperror_retried_then_none(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
    errs = [httpx.RemoteProtocolError("proto") for _ in range(hc.HTTP_RETRIES + 1)]
    client = FakeAsyncClient(errs)
    _patch_get_client(monkeypatch, client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out is None
    assert len(client.stream_calls) == hc.HTTP_RETRIES + 1
    assert sleeps == [hc.RETRY_DELAY] * hc.HTTP_RETRIES


def test_http_get_async_httperror_then_success(monkeypatch):
    async def fake_sleep(s):
        return None

    monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
    ok = FakeAsyncResponse(status_code=200, chunks=[b"ok"])
    client = FakeAsyncClient([httpx.RemoteProtocolError("proto"), ok])
    _patch_get_client(monkeypatch, client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out.text == "ok"
    assert len(client.stream_calls) == 2


def test_http_get_async_429_unparsable_retry_after_uses_default(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
    throttled = FakeAsyncResponse(status_code=429, is_success=False, headers={"Retry-After": "soon"})
    ok = FakeAsyncResponse(status_code=200, chunks=[b"after"])
    client = FakeAsyncClient([throttled, ok])
    _patch_get_client(monkeypatch, client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out.text == "after"
    assert sleeps == [hc.RETRY_DELAY * 3]


def test_http_get_async_429_clamps_retry_after_max(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
    throttled = FakeAsyncResponse(status_code=429, is_success=False, headers={"Retry-After": "9999"})
    ok = FakeAsyncResponse(status_code=200, chunks=[b"x"])
    client = FakeAsyncClient([throttled, ok])
    _patch_get_client(monkeypatch, client)
    _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert sleeps == [120.0]


def test_http_get_async_content_length_non_numeric_ignored(monkeypatch):
    monkeypatch.setattr(hc, "HTTP_MAX_RESPONSE_SIZE", 100)
    resp = FakeAsyncResponse(status_code=200, headers={"Content-Length": "abc"}, chunks=[b"body"])
    client = FakeAsyncClient([resp])
    _patch_get_client(monkeypatch, client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert isinstance(out, hc._AsyncResp)
    assert out.text == "body"


def test_http_get_async_500_retries_until_exhausted(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
    resps = [FakeAsyncResponse(status_code=500, is_success=False) for _ in range(hc.HTTP_RETRIES + 1)]
    client = FakeAsyncClient(resps)
    _patch_get_client(monkeypatch, client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out is None
    assert len(client.stream_calls) == hc.HTTP_RETRIES + 1
    assert sleeps == [hc.RETRY_DELAY] * hc.HTTP_RETRIES
