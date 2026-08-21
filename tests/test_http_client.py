import asyncio

import pytest
import requests as req

import engine.scraping.http_client as hc


@pytest.fixture(autouse=True)
def _isolate_module_state(monkeypatch):
    saved_cache = dict(hc._session_cache)
    saved_order = list(hc._session_keys_order)
    saved_async = dict(hc._async_client_state)
    monkeypatch.setattr(hc.time, "sleep", lambda *a, **k: None)
    yield
    hc._session_cache.clear()
    hc._session_cache.update(saved_cache)
    hc._session_keys_order[:] = saved_order
    hc._async_client_state.clear()
    hc._async_client_state.update(saved_async)


class FakeResponse:
    def __init__(self, status_code=200, ok=None, headers=None, chunks=(b"hello",), raise_iter=None):
        self.status_code = status_code
        self.ok = (status_code == 200) if ok is None else ok
        self.headers = dict(headers or {})
        self._chunks = list(chunks)
        self._raise_iter = raise_iter
        self.closed = False
        self.iter_calls = 0
        self.encoding = None
        self._content = None
        self._content_consumed = False

    def iter_content(self, size):
        self.iter_calls += 1
        if self._raise_iter is not None:
            raise self._raise_iter
        yield from self._chunks

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []
        self.headers = {}
        self.cookies = _FakeCookieJar()
        self.closed = False
        self.mounted = {}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def mount(self, prefix, adapter):
        self.mounted[prefix] = adapter

    def close(self):
        self.closed = True


class _FakeCookieJar:
    def __init__(self):
        self.set_calls = []
        self._cleared = False

    def set(self, name, value, **kwargs):
        self.set_calls.append((name, value, kwargs))

    def clear(self):
        self._cleared = True


def test_cookies_cache_key_anonymous_for_empty():
    assert hc._cookies_cache_key([]) == "anonymous"
    assert hc._cookies_cache_key(None) == "anonymous"


def test_cookies_cache_key_order_independent_and_deterministic():
    a = [{"name": "s", "value": "1"}, {"name": "t", "value": "2"}]
    b = [{"name": "t", "value": "2"}, {"name": "s", "value": "1"}]
    assert hc._cookies_cache_key(a) == hc._cookies_cache_key(b)
    assert hc._cookies_cache_key(a) != "anonymous"


def test_cookies_cache_key_distinguishes_values():
    a = [{"name": "s", "value": "1"}]
    b = [{"name": "s", "value": "2"}]
    assert hc._cookies_cache_key(a) != hc._cookies_cache_key(b)


def test_cookies_cache_key_skips_nameless_and_nondict():
    only_named = [{"name": "s", "value": "1"}]
    mixed = [{"name": "s", "value": "1"}, {"value": "x"}, "notadict", {"name": "", "value": "y"}]
    assert hc._cookies_cache_key(mixed) == hc._cookies_cache_key(only_named)


def test_cookies_dict_filters_and_maps():
    cookies = [
        {"name": "a", "value": "1"},
        {"name": "b", "value": None},
        {"value": "noname"},
        "bad",
        {"name": "c", "value": ""},
    ]
    assert hc._cookies_dict(cookies) == {"a": "1", "c": ""}


def test_cookies_dict_empty():
    assert hc._cookies_dict(None) == {}
    assert hc._cookies_dict([]) == {}


def test_build_session_sets_headers_and_cookies(monkeypatch):
    monkeypatch.setattr(hc.req, "Session", lambda: FakeSession([]))
    cookies = [
        {"name": "tok", "value": "v", "domain": "d", "path": "/p"},
        {"name": "skip", "value": ""},
        {"value": "noname"},
    ]
    s = hc._build_session(cookies)
    assert s.headers["User-Agent"] == hc.USER_AGENT
    assert s.headers["Referer"] == hc.SITE_URL + "/"
    assert "https://" in s.mounted and "http://" in s.mounted
    assert s.cookies.set_calls == [("tok", "v", {"domain": "d", "path": "/p"})]


def test_get_session_caches_and_reuses(monkeypatch):
    built = []

    def fake_build(cookies):
        sess = FakeSession([])
        built.append(sess)
        return sess

    monkeypatch.setattr(hc, "_build_session", fake_build)
    cookies = [{"name": "a", "value": "1"}]
    first = hc._get_session(cookies)
    second = hc._get_session(cookies)
    assert first is second
    assert len(built) == 1
    assert hc._session_keys_order == [hc._cookies_cache_key(cookies)]


def test_get_session_lru_reorders_on_hit(monkeypatch):
    monkeypatch.setattr(hc, "SESSION_CACHE_MAX", 8)
    monkeypatch.setattr(hc, "_build_session", lambda cookies: FakeSession([]))
    ck_a = [{"name": "a", "value": "1"}]
    ck_b = [{"name": "b", "value": "2"}]
    hc._get_session(ck_a)
    hc._get_session(ck_b)
    key_a = hc._cookies_cache_key(ck_a)
    key_b = hc._cookies_cache_key(ck_b)
    assert hc._session_keys_order == [key_a, key_b]
    hc._get_session(ck_a)
    assert hc._session_keys_order == [key_b, key_a]


def test_get_session_lru_eviction_closes_oldest(monkeypatch):
    monkeypatch.setattr(hc, "SESSION_CACHE_MAX", 2)
    monkeypatch.setattr(hc, "_build_session", lambda cookies: FakeSession([]))
    ck1 = [{"name": "x", "value": "1"}]
    ck2 = [{"name": "x", "value": "2"}]
    ck3 = [{"name": "x", "value": "3"}]
    s1 = hc._get_session(ck1)
    hc._get_session(ck2)
    assert s1.closed is False
    hc._get_session(ck3)
    assert s1.closed is True
    assert hc._cookies_cache_key(ck1) not in hc._session_cache
    assert len(hc._session_cache) == 2
    assert set(hc._session_keys_order) == {
        hc._cookies_cache_key(ck2),
        hc._cookies_cache_key(ck3),
    }


def test_clear_session_cache_empties_dicts():
    hc._session_cache["k"] = object()
    hc._session_keys_order.append("k")
    hc.clear_session_cache()
    assert hc._session_cache == {}
    assert hc._session_keys_order == []


def test_clear_session_cache_clears_async_client_cookies():
    jar = _FakeCookieJar()

    class _Client:
        cookies = jar

    hc._async_client_state["client"] = _Client()
    hc.clear_session_cache()
    assert jar._cleared is True


def test_lire_corps_borne_joins_chunks():
    r = FakeResponse(chunks=[b"ab", b"", b"cd"])
    out = hc._lire_corps_borne(r, "http://x")
    assert out == b"abcd"


def test_lire_corps_borne_size_cap_returns_none(monkeypatch):
    monkeypatch.setattr(hc, "HTTP_MAX_RESPONSE_SIZE", 3)
    r = FakeResponse(chunks=[b"aa", b"bb"])
    assert hc._lire_corps_borne(r, "http://x") is None


def test_lire_corps_borne_under_cap_ok(monkeypatch):
    monkeypatch.setattr(hc, "HTTP_MAX_RESPONSE_SIZE", 4)
    r = FakeResponse(chunks=[b"ab", b"cd"])
    assert hc._lire_corps_borne(r, "http://x") == b"abcd"


def test_lire_corps_borne_iter_exception_returns_none():
    r = FakeResponse(raise_iter=req.exceptions.ChunkedEncodingError("boom"))
    assert hc._lire_corps_borne(r, "http://x") is None


def test_reinjecter_corps_sets_content():
    r = FakeResponse()
    out = hc._reinjecter_corps_lu_en_streaming(r, b"body")
    assert out is r
    assert r._content == b"body"
    assert r._content_consumed is True
    assert r.encoding == "utf-8"


def test_http_get_success_returns_response_with_body():
    resp = FakeResponse(status_code=200, chunks=[b"page", b"data"])
    session = FakeSession([resp])
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is resp
    assert out._content == b"pagedata"
    assert resp.closed is True


def test_http_get_relative_url_prefixed():
    resp = FakeResponse(status_code=200, chunks=[b"ok"])
    session = FakeSession([resp])
    hc._http_get(session, "/catalogue")
    assert session.calls[0][0] == hc.SITE_URL + "/catalogue"


def test_http_get_permanent_error_no_retry():
    resp = FakeResponse(status_code=404, ok=False)
    session = FakeSession([resp])
    out = hc._http_get(session, "https://anime-sama.to/missing")
    assert out is None
    assert len(session.calls) == 1
    assert resp.closed is True


def test_http_get_403_permanent_no_retry():
    resp = FakeResponse(status_code=403, ok=False)
    session = FakeSession([resp])
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is None
    assert len(session.calls) == 1


def test_http_get_429_reads_retry_after_then_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(hc.time, "sleep", lambda s: sleeps.append(s))
    throttled = FakeResponse(status_code=429, ok=False, headers={"Retry-After": "5"})
    ok = FakeResponse(status_code=200, chunks=[b"done"])
    session = FakeSession([throttled, ok])
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is ok
    assert sleeps == [5.0]
    assert len(session.calls) == 2


def test_http_get_429_clamps_retry_after_max(monkeypatch):
    sleeps = []
    monkeypatch.setattr(hc.time, "sleep", lambda s: sleeps.append(s))
    throttled = FakeResponse(status_code=429, ok=False, headers={"Retry-After": "9999"})
    ok = FakeResponse(status_code=200, chunks=[b"x"])
    session = FakeSession([throttled, ok])
    hc._http_get(session, "https://anime-sama.to/x")
    assert sleeps == [120.0]


def test_http_get_429_bad_retry_after_uses_default(monkeypatch):
    sleeps = []
    monkeypatch.setattr(hc.time, "sleep", lambda s: sleeps.append(s))
    throttled = FakeResponse(status_code=429, ok=False, headers={"Retry-After": "soon"})
    ok = FakeResponse(status_code=200, chunks=[b"x"])
    session = FakeSession([throttled, ok])
    hc._http_get(session, "https://anime-sama.to/x")
    assert sleeps == [hc.RETRY_DELAY * 3]


def test_http_get_content_length_over_cap(monkeypatch):
    monkeypatch.setattr(hc, "HTTP_MAX_RESPONSE_SIZE", 100)
    resp = FakeResponse(status_code=200, headers={"Content-Length": "999"})
    session = FakeSession([resp])
    out = hc._http_get(session, "https://anime-sama.to/big")
    assert out is None
    assert resp.closed is True
    assert resp.iter_calls == 0


def test_http_get_content_length_non_numeric_ignored(monkeypatch):
    monkeypatch.setattr(hc, "HTTP_MAX_RESPONSE_SIZE", 100)
    resp = FakeResponse(status_code=200, headers={"Content-Length": "abc"}, chunks=[b"ok"])
    session = FakeSession([resp])
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is resp
    assert out._content == b"ok"


def test_http_get_body_over_cap_returns_none(monkeypatch):
    monkeypatch.setattr(hc, "HTTP_MAX_RESPONSE_SIZE", 3)
    resp = FakeResponse(status_code=200, chunks=[b"aa", b"bb"])
    session = FakeSession([resp])
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is None
    assert resp.closed is True


def test_http_get_sslerror_no_retry():
    session = FakeSession([req.exceptions.SSLError("bad cert")])
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is None
    assert len(session.calls) == 1


def test_http_get_connection_error_retried_then_none(monkeypatch):
    sleeps = []
    monkeypatch.setattr(hc.time, "sleep", lambda s: sleeps.append(s))
    errs = [req.exceptions.ConnectionError("c")] * (hc.HTTP_RETRIES + 1)
    session = FakeSession(errs)
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is None
    assert len(session.calls) == hc.HTTP_RETRIES + 1
    assert len(sleeps) == hc.HTTP_RETRIES


def test_http_get_connection_error_then_success(monkeypatch):
    monkeypatch.setattr(hc.time, "sleep", lambda *a, **k: None)
    ok = FakeResponse(status_code=200, chunks=[b"r"])
    session = FakeSession([req.exceptions.ConnectionError("c"), ok])
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is ok


def test_http_get_timeout_retried_then_none(monkeypatch):
    monkeypatch.setattr(hc.time, "sleep", lambda *a, **k: None)
    errs = [req.exceptions.Timeout()] * (hc.HTTP_RETRIES + 1)
    session = FakeSession(errs)
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is None
    assert len(session.calls) == hc.HTTP_RETRIES + 1


def test_http_get_generic_5xx_retries_until_exhausted(monkeypatch):
    sleeps = []
    monkeypatch.setattr(hc.time, "sleep", lambda s: sleeps.append(s))
    resps = [FakeResponse(status_code=500, ok=False) for _ in range(hc.HTTP_RETRIES + 1)]
    session = FakeSession(resps)
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is None
    assert len(session.calls) == hc.HTTP_RETRIES + 1
    assert len(sleeps) == hc.HTTP_RETRIES


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
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.stream_calls = []
        self.closed = False
        self.cookies = _FakeCookieJar()

    def stream(self, method, url, **kwargs):
        self.stream_calls.append((method, url, kwargs))
        item = self._scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return _AsyncStreamCtx(item)

    async def aclose(self):
        self.closed = True


def _run(coro):
    return asyncio.run(coro)


def test_http_get_async_success(monkeypatch):
    resp = FakeAsyncResponse(status_code=200, chunks=[b"foo", b"bar"])
    client = FakeAsyncClient([resp])

    async def fake_get_client():
        return client

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", [{"name": "c", "value": "1"}]))
    assert isinstance(out, hc._AsyncResp)
    assert out.status_code == 200
    assert out.text == "foobar"
    assert client.stream_calls[0][2]["cookies"] == {"c": "1"}


def test_http_get_async_relative_url(monkeypatch):
    resp = FakeAsyncResponse(status_code=200, chunks=[b"x"])
    client = FakeAsyncClient([resp])

    async def fake_get_client():
        return client

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)
    _run(hc._http_get_async("/catalogue", None))
    assert client.stream_calls[0][1] == hc.SITE_URL + "/catalogue"


def test_http_get_async_no_client_returns_none(monkeypatch):
    async def fake_get_client():
        return None

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out is None


def test_http_get_async_403_permanent(monkeypatch):
    resp = FakeAsyncResponse(status_code=403, is_success=False)
    client = FakeAsyncClient([resp])

    async def fake_get_client():
        return client

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out is None
    assert len(client.stream_calls) == 1


def test_http_get_async_429_then_success(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
    throttled = FakeAsyncResponse(status_code=429, is_success=False, headers={"Retry-After": "7"})
    ok = FakeAsyncResponse(status_code=200, chunks=[b"done"])
    client = FakeAsyncClient([throttled, ok])

    async def fake_get_client():
        return client

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out.text == "done"
    assert sleeps == [7.0]
    assert len(client.stream_calls) == 2


def test_http_get_async_content_length_over_cap(monkeypatch):
    monkeypatch.setattr(hc, "HTTP_MAX_RESPONSE_SIZE", 10)
    resp = FakeAsyncResponse(status_code=200, headers={"Content-Length": "9999"})
    client = FakeAsyncClient([resp])

    async def fake_get_client():
        return client

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out is None


def test_http_get_async_body_over_cap(monkeypatch):
    monkeypatch.setattr(hc, "HTTP_MAX_RESPONSE_SIZE", 3)
    resp = FakeAsyncResponse(status_code=200, chunks=[b"aa", b"bb"])
    client = FakeAsyncClient([resp])

    async def fake_get_client():
        return client

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out is None


def test_http_get_async_timeout_retried_then_none(monkeypatch):
    import httpx

    async def fake_sleep(s):
        return None

    monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
    errs = [httpx.TimeoutException("t")] * (hc.HTTP_RETRIES + 1)
    client = FakeAsyncClient(errs)

    async def fake_get_client():
        return client

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert out is None
    assert len(client.stream_calls) == hc.HTTP_RETRIES + 1


def test_close_async_client_resets_state_and_closes(monkeypatch):
    client = FakeAsyncClient([])
    hc._async_client_state["client"] = client
    hc._async_client_state["loop"] = object()
    _run(hc.close_async_client())
    assert client.closed is True
    assert hc._async_client_state["client"] is None
    assert hc._async_client_state["loop"] is None


def test_close_async_client_noop_when_empty():
    hc._async_client_state["client"] = None
    hc._async_client_state["loop"] = None
    _run(hc.close_async_client())
    assert hc._async_client_state["client"] is None


def test_http_get_dispatch_sync_path(monkeypatch):
    monkeypatch.setattr(hc, "_HTTP_ASYNC", False)
    sentinel = FakeResponse(status_code=200, chunks=[b"sync"])
    fake_session = object()
    monkeypatch.setattr(hc, "_get_session", lambda cookies: fake_session)
    seen = {}

    def fake_sync(session, url):
        seen["session"] = session
        seen["url"] = url
        return sentinel

    monkeypatch.setattr(hc, "_http_get", fake_sync)
    out = _run(hc.http_get("https://anime-sama.to/x", [{"name": "c", "value": "1"}]))
    assert out is sentinel
    assert seen["session"] is fake_session
    assert seen["url"] == "https://anime-sama.to/x"


def test_http_get_dispatch_async_path(monkeypatch):
    monkeypatch.setattr(hc, "_HTTP_ASYNC", True)
    sentinel = object()

    async def fake_async(url, cookies):
        return sentinel

    monkeypatch.setattr(hc, "_http_get_async", fake_async)

    def boom(*a, **k):
        raise AssertionError("sync path must not run")

    monkeypatch.setattr(hc, "_http_get", boom)
    out = _run(hc.http_get("https://anime-sama.to/x", None))
    assert out is sentinel
