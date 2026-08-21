import asyncio
import importlib
import sys
import types

import pytest

import engine.cache.disk_cache as disk_cache
import engine.cache.ttl_cache as ttl_cache
import engine.config.settings as settings
import engine.config.user_settings as user_settings
import engine.download._helpers as helpers
import engine.observability.metrics as metrics_mod
import engine.scraping._cache as scache
import engine.scraping.http_client as hc
import engine.scraping.scraper as scraper
import engine.utils.aio as aio
import engine.utils.circuit_breaker as cb
import engine.utils.security as security
from engine.domain.exceptions import RateLimitError, UnsafeUrlError


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_http_client_state():
    saved_cache = dict(hc._session_cache)
    saved_order = list(hc._session_keys_order)
    saved_async = dict(hc._async_client_state)
    yield
    hc._session_cache.clear()
    hc._session_cache.update(saved_cache)
    hc._session_keys_order[:] = saved_order
    hc._async_client_state.clear()
    hc._async_client_state.update(saved_async)


class _FakeRequestException(Exception):
    pass


class _ScriptedSession:
    def __init__(self, behaviours):
        self._behaviours = list(behaviours)
        self.get_calls = 0

    def get(self, url, **kwargs):
        self.get_calls += 1
        item = self._behaviours.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_is_safe_url_urlparse_exception_returns_false(monkeypatch):
    def boom(_url):
        raise ValueError("bad parse")

    monkeypatch.setattr(hc, "urlparse", boom)
    assert hc._is_safe_url("https://anime-sama.to/x") is False


def test_is_safe_url_empty_host_returns_false():
    assert hc._is_safe_url("http://") is False


def test_get_session_cache_hit_missing_order_entry(monkeypatch):
    monkeypatch.setattr(hc, "_session_cache", {})
    monkeypatch.setattr(hc, "_session_keys_order", [])
    key = hc._cookies_cache_key(None)
    sentinel = object()
    hc._session_cache[key] = sentinel
    out = hc._get_session(None)
    assert out is sentinel
    assert hc._session_keys_order == [key]


def test_get_session_eviction_swallows_close_error(monkeypatch):
    monkeypatch.setattr(hc, "_session_cache", {})
    monkeypatch.setattr(hc, "_session_keys_order", [])
    monkeypatch.setattr(hc, "SESSION_CACHE_MAX", 1)

    class _BoomCloseSession:
        def close(self):
            raise RuntimeError("close failed")

    old_key = "old"
    hc._session_cache[old_key] = _BoomCloseSession()
    hc._session_keys_order.append(old_key)

    built = object()
    monkeypatch.setattr(hc, "_build_session", lambda cookies: built)
    out = hc._get_session([{"name": "n", "value": "v"}])
    assert out is built
    assert old_key not in hc._session_cache


def test_http_get_request_exception_retries_then_debug(monkeypatch):
    monkeypatch.setattr(hc.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(hc.req.exceptions, "RequestException", _FakeRequestException, raising=False)
    errs = [_FakeRequestException("boom") for _ in range(hc.HTTP_RETRIES + 1)]
    session = _ScriptedSession(errs)
    out = hc._http_get(session, "https://anime-sama.to/x")
    assert out is None
    assert session.get_calls == hc.HTTP_RETRIES + 1


def test_close_async_client_swallows_aclose_error():
    class _BoomClient:
        async def aclose(self):
            raise RuntimeError("nope")

    hc._async_client_state["client"] = _BoomClient()
    hc._async_client_state["loop"] = object()
    _run(hc.close_async_client())
    assert hc._async_client_state["client"] is None
    assert hc._async_client_state["loop"] is None


class _FakeAsyncResponse:
    def __init__(self, status_code, is_success, headers, chunks):
        self.status_code = status_code
        self.is_success = is_success
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


class _FakeAsyncClient:
    def __init__(self, resp):
        self._resp = resp
        self.stream_calls = 0

    def stream(self, method, url, **kwargs):
        self.stream_calls += 1
        return _AsyncStreamCtx(self._resp)


def _install_fake_httpx(monkeypatch):
    import httpx as real_httpx

    mod = types.ModuleType("httpx")
    mod.TimeoutException = real_httpx.TimeoutException
    mod.ConnectError = real_httpx.ConnectError
    mod.HTTPError = real_httpx.HTTPError
    monkeypatch.setitem(sys.modules, "httpx", mod)
    return mod


def test_http_get_async_skips_empty_chunk(monkeypatch):
    _install_fake_httpx(monkeypatch)
    resp = _FakeAsyncResponse(200, True, {}, [b"", b"data"])
    client = _FakeAsyncClient(resp)

    async def fake_get_client():
        return client

    monkeypatch.setattr(hc, "_get_async_client", fake_get_client)
    out = _run(hc._http_get_async("https://anime-sama.to/x", None))
    assert isinstance(out, hc._AsyncResp)
    assert out.text == "data"
    assert client.stream_calls == 1


def test_http_get_async_branch_falls_back_to_sync_when_httpx_missing(monkeypatch):
    monkeypatch.setattr(hc, "_HTTP_ASYNC", True)
    monkeypatch.setitem(sys.modules, "httpx", None)
    captured = {}

    async def fake_to_thread(fn, session, url):
        captured["session"] = session
        captured["url"] = url
        return "sync-result"

    monkeypatch.setattr(hc.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(hc, "_get_session", lambda cookies: "the-session")
    out = _run(hc.http_get("https://anime-sama.to/x", None))
    assert out == "sync-result"
    assert captured["session"] == "the-session"


def test_safe_mkdir_fallback_swallows_inner_error(monkeypatch):
    class _BoomFallback:
        def mkdir(self, *a, **k):
            raise OSError("denied even fallback")

        def __str__(self):
            return "<boom-fallback>"

    class _FakeRoot:
        def __truediv__(self, other):
            assert other == "downloads"
            return _BoomFallback()

    monkeypatch.setattr(settings, "ROOT_DIR", _FakeRoot())

    class _BoomTarget:
        def mkdir(self, *a, **k):
            raise OSError("denied")

        def __str__(self):
            return "<boom-target>"

    out = settings._safe_mkdir(_BoomTarget(), "DOWNLOADS_DIR")
    assert isinstance(out, _BoomFallback)


def _reload_settings_with_env(monkeypatch, tmp_path, env):
    monkeypatch.setenv("DOWNLOADS_DIR", str(tmp_path / "dl"))
    monkeypatch.setenv("SCANS_DIR", str(tmp_path / "sc"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    importlib.reload(settings)


def test_settings_domain_delays_json_valid_then_restore(monkeypatch, tmp_path):
    try:
        _reload_settings_with_env(
            monkeypatch, tmp_path, {"DOMAIN_DELAYS_JSON": '{"example.com": 7.5}'}
        )
        assert settings.DOMAIN_MIN_DELAYS["example.com"] == 7.5
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


def test_settings_domain_delays_json_invalid_then_restore(monkeypatch, tmp_path):
    try:
        _reload_settings_with_env(
            monkeypatch, tmp_path, {"DOMAIN_DELAYS_JSON": "{not json"}
        )
        assert "example.com" not in settings.DOMAIN_MIN_DELAYS
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


def test_settings_ytdlp_extra_domains_valid_then_restore(monkeypatch, tmp_path):
    try:
        _reload_settings_with_env(
            monkeypatch, tmp_path, {"YTDLP_EXTRA_DOMAINS": '["newhost.tld"]'}
        )
        assert "newhost.tld" in settings.YTDLP_FIRST_DOMAINS
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


def test_settings_ytdlp_extra_domains_invalid_then_restore(monkeypatch, tmp_path):
    try:
        _reload_settings_with_env(
            monkeypatch, tmp_path, {"YTDLP_EXTRA_DOMAINS": "{bad"}
        )
        assert "newhost.tld" not in settings.YTDLP_FIRST_DOMAINS
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


def test_settings_dotenv_import_error_swallowed_then_restore(monkeypatch, tmp_path):
    try:
        monkeypatch.setitem(sys.modules, "dotenv", None)
        _reload_settings_with_env(monkeypatch, tmp_path, {})
        assert settings.PORT >= 1
    finally:
        monkeypatch.undo()
        importlib.reload(settings)


class _FakeTtyStream:
    def isatty(self):
        return True


def test_logging_setup_color_branch_on_tty_then_restore(monkeypatch):
    from engine.config import logging_setup as ls

    try:
        monkeypatch.setattr(ls.sys, "stdout", _FakeTtyStream())
        monkeypatch.setattr(ls.os, "environ", {}, raising=True)
        monkeypatch.setattr(ls.sys, "platform", "linux")
        importlib.reload(ls)
        assert ls._COLOR_OK is True
        assert ls.C.RESET == "\033[0m"
        assert ls.C.GREEN == "\033[32m"
    finally:
        monkeypatch.undo()
        importlib.reload(ls)


def test_logging_setup_unknown_noise_mro_returns_false():
    from engine.config import logging_setup as ls

    class _TargetClosedError(Exception):
        pass

    class _Sub(_TargetClosedError):
        pass

    _TargetClosedError.__name__ = "TargetClosedError"
    flt = ls._AsyncioNoiseFilter()
    exc = _Sub("closed via mro")
    record = ls.logging.LogRecord(
        name="asyncio",
        level=ls.logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Future exception was never retrieved %s",
        args=("detail",),
        exc_info=(type(exc), exc, None),
    )
    assert flt.filter(record) is False


def test_logging_setup_noise_message_pattern_returns_false():
    from engine.config import logging_setup as ls

    flt = ls._AsyncioNoiseFilter()
    record = ls.logging.LogRecord(
        name="asyncio",
        level=ls.logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Future exception was never retrieved: Target closed",
        args=(),
        exc_info=None,
    )
    assert flt.filter(record) is False


def test_logging_setup_success_method_logs_when_enabled():
    from engine.config import logging_setup as ls

    captured = {}

    class _Logger:
        def isEnabledFor(self, level):
            captured["enabled_for"] = level
            return True

        def _log(self, level, message, args, **kwargs):
            captured["log"] = (level, message, args)

    ls._log_success(_Logger(), "well done", "a", "b")
    assert captured["enabled_for"] == ls.SUCCESS_LEVEL
    assert captured["log"][0] == ls.SUCCESS_LEVEL
    assert captured["log"][1] == "well done"
    assert captured["log"][2] == ("a", "b")


def test_ll_locked_swallows_exception_returns_true():
    class _BoomObj:
        def locked(self):
            raise RuntimeError("cannot check lock")

    class _LL:
        _obj = _BoomObj()

    assert scache._ll_locked(_LL()) is True


def test_scraper_cache_fav_lock_returns_loop_lock():
    c = scache.ScraperCache()

    async def main():
        return c.fav_lock()

    lock = _run(main())
    assert isinstance(lock, asyncio.Lock)


def test_purge_ep_expired_drops_old_entries(monkeypatch):
    c = scache.ScraperCache()
    clock = [1000.0]
    monkeypatch.setattr(scache.time, "time", lambda: clock[0])
    c.set_ep("k1", {"v": 1})
    clock[0] += scache.EP_CACHE_TTL + 1
    removed = c.purge_ep_expired()
    assert removed == 1
    assert "k1" not in c._ep


def test_invalidate_ep_with_catalogue_match():
    from engine.scraping.site.animessama import SITE_URL

    c = scache.ScraperCache()
    catalogue_key = f"{SITE_URL}/catalogue/naruto"
    c._ep[catalogue_key] = ({"v": 1}, 0.0)
    c.invalidate_ep(f"{SITE_URL}/catalogue/naruto?page=2")
    assert catalogue_key not in c._ep


def test_scraper_invalidate_fav_cache():
    captured = {}

    class _Cache:
        def invalidate_fav(self):
            captured["fav"] = True

    original = scraper.cache
    scraper.cache = _Cache()
    try:
        _run(scraper.invalidate_fav_cache())
    finally:
        scraper.cache = original
    assert captured["fav"] is True


def test_scraper_invalidate_ep_cache_none_and_url():
    captured = []

    class _Cache:
        def invalidate_ep(self, url):
            captured.append(url)

    original = scraper.cache
    scraper.cache = _Cache()
    try:
        _run(scraper.invalidate_ep_cache(None))
        _run(scraper.invalidate_ep_cache("https://anime-sama.to/catalogue/x?page=1"))
    finally:
        scraper.cache = original
    assert captured == [None, "https://anime-sama.to/catalogue/x?page=1"]


def test_user_settings_save_returns_false_on_oserror(tmp_path, monkeypatch):
    target = tmp_path / "s.json"
    monkeypatch.setattr(user_settings, "SETTINGS_FILE", target)

    def _boom(*a, **k):
        raise OSError("denied")

    monkeypatch.setattr(user_settings.os, "replace", _boom)
    assert user_settings.save_settings({"a": 1}) is False


def test_validate_external_url_urlparse_exception(monkeypatch):
    def boom(_url):
        raise ValueError("malformed")

    monkeypatch.setattr(security, "urlparse", boom)
    with pytest.raises(UnsafeUrlError):
        security.validate_external_url("https://example.com")


def test_ipv4_legacy_address_value_error(monkeypatch):
    monkeypatch.setattr(security.socket, "inet_aton", lambda host: b"\x01\x02\x03")
    assert security._ipv4_legacy("anything") is None


def test_disk_cache_save_swallows_oserror(monkeypatch):
    dc = disk_cache.DiskCache("x", ttl=100.0)
    try:
        def _boom(*a, **k):
            raise OSError("cannot mkdir")

        monkeypatch.setattr(disk_cache.Path, "mkdir", _boom)

        dc.set("k", "v")
        assert dc.get("k") is None
    finally:
        dc.close()


def test_ttl_cache_get_swallows_metrics_error(monkeypatch):
    c = ttl_cache.TTLCache(ttl=100.0, name="t")
    c.set("payload")

    def boom_incr(*a, **k):
        raise RuntimeError("metrics down")

    monkeypatch.setattr(metrics_mod.metrics, "incr", boom_incr)
    assert c.get() == "payload"


def test_metrics_observe_bad_value_ignored():
    m = metrics_mod.Metrics()
    m.observe("lat", object())
    assert m.percentiles("lat") == {}


def test_metrics_percentile_empty_returns_zero():
    assert metrics_mod.Metrics._percentile([], 50) == 0.0


def test_circuit_breaker_repr():
    breaker = cb.CircuitBreaker("svc", failure_threshold=3)
    text = repr(breaker)
    assert "CircuitBreaker(name='svc'" in text
    assert "state=closed" in text
    assert "failures=0/3" in text


def test_aio_loop_local_fast_path_returns_cached():
    ll = aio.LoopLocal(lambda: object())

    async def main():
        first = ll.get()
        second = ll.get()
        return first, second

    first, second = _run(main())
    assert first is second


def test_aio_require_raises_without_running_loop():
    ll = aio.LoopLocal(lambda: object())
    with pytest.raises(RuntimeError):
        ll.require()


def test_helpers_espace_disque_walk_breaks_at_root(monkeypatch):
    monkeypatch.setattr(helpers.os.path, "isdir", lambda p: False)
    assert helpers.espace_disque_suffisant("X:/") is True


def test_rate_limit_error_carries_domain():
    err = RateLimitError("limited", domain="example.com")
    assert err.domain == "example.com"
    assert str(err) == "limited"
