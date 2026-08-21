import asyncio
import json

import engine.scraping.http_client as hc
import engine.scraping.search as search


class _AdvancingClock:
    def __init__(self, step):
        self.t = 0.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


def test_save_types_cache_holds_lock_during_write(monkeypatch, tmp_path):
    monkeypatch.setattr(search, "_TYPES_FILE", tmp_path / "scan_types.json")
    observed = {}
    real_dump = json.dump

    def _probing_dump(obj, fp, *a, **k):
        got = search._types_cache_lock.acquire(blocking=False)
        observed["held"] = not got
        if got:
            search._types_cache_lock.release()
        return real_dump(obj, fp, *a, **k)

    monkeypatch.setattr(search.json, "dump", _probing_dump)

    with search._types_cache_lock:
        snap = dict(search._types_cache)
        search._types_cache.clear()
        search._types_cache["https://x/a"] = "scan"
    try:
        search._save_types_cache()
    finally:
        with search._types_cache_lock:
            search._types_cache.clear()
            search._types_cache.update(snap)

    assert observed.get("held") is True


class _FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_clear_session_cache_closes_cached_sessions():
    s1, s2 = _FakeSession(), _FakeSession()
    with hc._session_lock:
        hc._session_cache.clear()
        hc._session_keys_order.clear()
        hc._session_cache["k1"] = s1
        hc._session_cache["k2"] = s2
        hc._session_keys_order.extend(["k1", "k2"])

    hc.clear_session_cache()

    assert s1.closed is True
    assert s2.closed is True
    assert hc._session_cache == {}
    assert hc._session_keys_order == []


class _Resp500:
    def __init__(self):
        self.headers: dict = {}
        self.is_success = False
        self.status_code = 500


class _StreamCM:
    def __init__(self, resp):
        self._r = resp

    async def __aenter__(self):
        return self._r

    async def __aexit__(self, *exc):
        return False


class _Client500:
    def __init__(self):
        self.calls = 0

    def stream(self, *a, **k):
        self.calls += 1
        return _StreamCM(_Resp500())


def test_http_get_async_aborts_on_total_deadline(monkeypatch):
    client = _Client500()

    async def _fake_client():
        return client

    async def _nosleep(*a, **k):
        return None

    monkeypatch.setattr(hc, "_get_async_client", _fake_client)
    monkeypatch.setattr(hc, "HTTP_TOTAL_DEADLINE", 2.5)
    monkeypatch.setattr(hc.time, "monotonic", _AdvancingClock(step=2.0))
    monkeypatch.setattr(hc.asyncio, "sleep", _nosleep)

    out = asyncio.run(hc._http_get_async("http://x/slow", None))

    assert out is None
    assert client.calls == 1


class _FakeQueue:
    _cancelled = None

    def emit(self, *a, **k):
        pass


def test_prefetch_deadline_scales_with_lecteur_count(monkeypatch):
    import engine.download.pipeline as pipeline

    monkeypatch.setattr(pipeline, "_PREFETCH_ENABLED", True)

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(pipeline.asyncio, "sleep", _no_sleep)

    lecteurs_list = [{"src": "u1"}, {"src": "u2"}, {"src": "u3"}]

    async def _lecteurs(url):
        return lecteurs_list

    monkeypatch.setattr("engine.scraping.scraper.get_lecteurs_async", _lecteurs)
    monkeypatch.setattr(pipeline, "partition_lecteurs", lambda lec: ([], list(lec)))

    captured = {}

    async def _fake_wait_for(aw, timeout=0):
        captured["timeout"] = timeout
        aw.close()
        return {"url": "https://cdn/x.m3u8", "headers": {}}

    monkeypatch.setattr(pipeline.asyncio, "wait_for", _fake_wait_for)

    asyncio.run(pipeline.prefetch_extraction({"url": "https://anime-sama.to/ep?scale"}, _FakeQueue()))

    n = len(lecteurs_list)
    assert captured["timeout"] == pipeline.TIMEOUT_LECTEUR_PAR + (n + 1) * pipeline.TIMEOUT_LECTEUR_SEQ


def test_save_settings_uses_unique_tmp(tmp_path, monkeypatch):
    import engine.config.user_settings as us

    target = tmp_path / "user_settings.json"
    monkeypatch.setattr(us, "_target", lambda: target)
    (tmp_path / "user_settings.tmp").mkdir()

    assert us.save_settings({"a": 1}) is True
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


class _SlowResp:
    def __init__(self):
        self.encoding = "utf-8"
        self.status_code = 200
        self.headers: dict = {}
        self.consumed = 0

    def iter_content(self, n):
        for _ in range(1000):
            self.consumed += 1
            yield b"x" * 1024

    def close(self):
        pass


def test_scan_fetch_text_aborts_on_body_deadline(monkeypatch):
    import engine.scraping.scan as scan

    resp = _SlowResp()

    class _Sess:
        def get(self, *a, **k):
            return resp

    monkeypatch.setattr(scan, "_get_session", lambda *a, **k: _Sess())
    monkeypatch.setattr(scan, "_BODY_DEADLINE", 6)
    monkeypatch.setattr(scan.time, "monotonic", _AdvancingClock(step=2.0))

    status, text = scan._fetch_text("http://x/slow")

    assert status == 200
    assert resp.consumed < 1000

