import asyncio

import pytest

import engine.download.pipeline as pipeline
from engine.download._domain_strategy import lecteur_url_valide, partition_lecteurs
from engine.download._runtime import _est_annule
from engine.download.extractor import browser_extractor as bx
from engine.download.interceptor import _est_bruit_attendu, _is_browser_alive


@pytest.fixture(autouse=True)
def _clear_ext_cache():
    """Snapshot-clear the module-level extraction cache before and after each test."""
    pipeline._ext_cache.clear()
    yield
    pipeline._ext_cache.clear()


def test_ext_cache_take_returns_fresh_value():
    """A freshly-set entry is returned by the first take."""
    pipeline._ext_cache_set("u", {"url": "x"})
    assert pipeline._ext_cache_take("u") == {"url": "x"}


def test_ext_cache_take_consumes_value_once():
    """The value is popped, so a second take yields None."""
    pipeline._ext_cache_set("u", {"url": "x"})
    pipeline._ext_cache_take("u")
    assert pipeline._ext_cache_take("u") is None


def test_ext_cache_take_missing_key_is_none():
    """Taking a never-set key returns None."""
    assert pipeline._ext_cache_take("absent") is None


def test_ext_cache_take_expired_entry_returns_none():
    """An entry older than the TTL is treated as absent."""
    stale_ts = pipeline.time.time() - pipeline._EXT_CACHE_TTL - 1
    pipeline._ext_cache["u"] = (stale_ts, {"url": "stale"})
    assert pipeline._ext_cache_take("u") is None


def test_ext_cache_take_expired_entry_is_evicted():
    """Reading a stale entry removes it from the cache dict."""
    stale_ts = pipeline.time.time() - pipeline._EXT_CACHE_TTL - 1
    pipeline._ext_cache["u"] = (stale_ts, {"url": "stale"})
    pipeline._ext_cache_take("u")
    assert "u" not in pipeline._ext_cache


def test_ext_cache_take_just_within_ttl_returns_value():
    """An entry well inside the TTL window is still served."""
    fresh_ts = pipeline.time.time() - 1.0
    pipeline._ext_cache["u"] = (fresh_ts, {"url": "fresh"})
    assert pipeline._ext_cache_take("u") == {"url": "fresh"}


def test_ext_cache_set_clears_when_over_fifty():
    """When the cache holds 51 entries, set() drops them all and keeps only the new one."""
    now = pipeline.time.time()
    for i in range(51):
        pipeline._ext_cache[f"k{i}"] = (now, {})
    pipeline._ext_cache_set("big", {"url": "z"})
    assert list(pipeline._ext_cache.keys()) == ["big"]


def test_ext_cache_set_under_threshold_keeps_existing():
    """Below the overflow threshold the existing entries are preserved."""
    now = pipeline.time.time()
    for i in range(10):
        pipeline._ext_cache[f"k{i}"] = (now, {})
    pipeline._ext_cache_set("extra", {"url": "z"})
    assert "k0" in pipeline._ext_cache
    assert "extra" in pipeline._ext_cache


class _RealQueueWithCancel:
    def __init__(self, flag) -> None:
        self._cancelled = flag

    def emit(self, *a, **k) -> None:
        raise AssertionError("real emit must not be called via SilentQueue")


class _RealQueueNoCancel:
    def emit(self, *a, **k) -> None:
        pass


def test_silent_queue_copies_cancel_flag():
    """The wrapper exposes the real queue's _cancelled so cancellation stays visible."""
    real = _RealQueueWithCancel([True])
    silent = pipeline._SilentQueue(real)
    assert silent._cancelled == [True]


def test_silent_queue_cancel_flag_observed_by_est_annule():
    """_est_annule reads the copied cancel flag through the wrapper."""
    real = _RealQueueWithCancel([True])
    silent = pipeline._SilentQueue(real)
    assert _est_annule(silent) is True


def test_silent_queue_defaults_cancel_to_none():
    """When the real object lacks _cancelled the wrapper stores None."""
    real = _RealQueueNoCancel()
    silent = pipeline._SilentQueue(real)
    assert silent._cancelled is None


def test_silent_queue_emit_is_noop_returns_none():
    """emit accepts arbitrary args and returns None without raising."""
    silent = pipeline._SilentQueue(_RealQueueNoCancel())
    assert silent.emit("episode_done", {"ep": "x"}, extra=1) is None


def test_est_bruit_attendu_message_in_exception_str():
    """A benign-named exception whose str() carries a noise pattern is treated as noise."""
    exc = ValueError("Target page, context or browser has been closed")
    assert _est_bruit_attendu({"exception": exc}) is True


def test_est_bruit_attendu_mro_walk_matches_named_base():
    """A subclass of a noise-named base is noise even when the leaf type name differs."""
    base = type("CancelledError", (Exception,), {})
    leaf = type("WeirdLeafName", (base,), {})
    assert _est_bruit_attendu({"exception": leaf()}) is True


def test_est_bruit_attendu_unrelated_exception_is_false():
    """An ordinary exception with no noise markers is not treated as noise."""
    assert _est_bruit_attendu({"exception": ValueError("disk full")}) is False


def test_is_browser_alive_none_is_false():
    """A None browser is never alive."""
    assert _is_browser_alive(None) is False


class _BrowserRaising:
    def is_connected(self):
        raise RuntimeError("transport gone")


class _BrowserConnected:
    def is_connected(self):
        return True


class _BrowserDisconnected:
    def is_connected(self):
        return False


def test_is_browser_alive_raising_is_connected_is_false():
    """An is_connected that raises is swallowed and reported as not alive."""
    assert _is_browser_alive(_BrowserRaising()) is False


def test_is_browser_alive_truthy_is_connected_is_true():
    """A connected browser is alive."""
    assert _is_browser_alive(_BrowserConnected()) is True


def test_is_browser_alive_falsy_is_connected_is_false():
    """A disconnected browser is not alive."""
    assert _is_browser_alive(_BrowserDisconnected()) is False


def test_score_url_secure_only():
    """A bare /secure/ URL with no type scores exactly the secure bonus."""
    assert bx._score_url("http://h/secure/x", "") == bx._SCORE_SECURE


def test_score_url_perf_type_adds_perf_bonus():
    """A perf-prefixed type contributes the perf bonus on top of the URL score."""
    assert bx._score_url("http://h/secure/x", "perf_observer") == bx._SCORE_SECURE + bx._SCORE_PERF


def test_score_url_hlsjs_type_adds_hlsjs_bonus():
    """The hlsjs_loadSource type contributes the hlsjs bonus."""
    assert bx._score_url("http://h/plain", "hlsjs_loadSource") == bx._SCORE_HLSJS


def test_score_url_components_are_additive():
    """A cdp_response master HLS m3u8 URL sums all matching component scores."""
    expected = bx._SCORE_M3U8 + bx._SCORE_MASTER + bx._SCORE_HLS_PATH + bx._SCORE_CDP
    assert bx._score_url("http://h/hls/master.m3u8", "cdp_response") == expected


class _FakePage:
    def __init__(self, html) -> None:
        self._html = html

    async def content(self) -> str:
        return self._html


def test_forensic_scan_extracts_bare_html_m3u8():
    """A bare inline master playlist URL is returned with type forensic_html and trailing slashes stripped."""
    html = "<html><body>watch https://cdn.example.com/master.m3u8?x=1\\ now</body></html>"
    results = asyncio.run(bx._forensic_scan(_FakePage(html)))
    html_hits = [r for r in results if r["type"] == "forensic_html"]
    assert html_hits == [{"url": "https://cdn.example.com/master.m3u8?x=1", "type": "forensic_html", "ts": 0}]


def test_forensic_scan_extracts_json_quoted_m3u8():
    """A JSON-quoted playlist URL is returned with type forensic_json."""
    html = '<script>var s = {"src":"https://cdn.example.com/v.m3u8"};</script>'
    results = asyncio.run(bx._forensic_scan(_FakePage(html)))
    json_hits = [r for r in results if r["type"] == "forensic_json"]
    assert json_hits == [{"url": "https://cdn.example.com/v.m3u8", "type": "forensic_json", "ts": 0}]


def test_partition_lecteurs_filters_non_dict_entries():
    """partition_lecteurs short-circuits on isinstance(l, dict), so non-dict entries are dropped not crashed."""
    valid = {"src": "https://x.com/a"}
    ytdlp, autres = partition_lecteurs([valid, "notadict", None])
    assert ytdlp + autres == [valid]


def test_lecteur_url_valide_raises_on_string_entry():
    """lecteur_url_valide assumes a mapping; a plain string has no .get and raises."""
    with pytest.raises(AttributeError):
        lecteur_url_valide("notadict")
