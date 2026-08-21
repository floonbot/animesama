import logging

import pytest

from engine.config import logging_setup as ls
from engine.scraping import anilist as anilist_mod
from engine.scraping import scan as scan_mod


class _FakeDisk:
    """Records get/set calls and serves a scripted get value."""

    def __init__(self, get_value=None):
        self.get_value = get_value
        self.get_calls = []
        self.set_calls = []

    def get(self, key):
        self.get_calls.append(key)
        return self.get_value

    def set(self, key, value):
        self.set_calls.append((key, value))


class _FakeResp:
    """Minimal requests-like response for anilist._fetch_sync."""

    def __init__(self, status_code=200, payload=None, raise_on_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("bad json")
        return self._payload


class _FakeStreamResp:
    """Fake streaming response for scan._fetch_text."""

    def __init__(self, status_code=200, chunks=None, encoding="utf-8"):
        self.status_code = status_code
        self.encoding = encoding
        self._chunks = chunks if chunks is not None else []
        self.closed = 0

    def iter_content(self, _size):
        yield from self._chunks

    def close(self):
        self.closed += 1


class _FakeSession:
    """Fake session whose get returns a scripted response or raises."""

    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.get_calls = 0

    def get(self, url, headers=None, timeout=None, stream=None):
        self.get_calls += 1
        if self._exc is not None:
            raise self._exc
        return self._response


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Re:Zero - Season 2!", "rezeroseason2"),
        (None, ""),
        ("   ", ""),
        ("Bleach", "bleach"),
    ],
)
def test_norm_handles_none_and_strips(raw, expected):
    """_norm tolerates None via the (s or '') guard and strips non-alnum."""
    assert anilist_mod._norm(raw) == expected


def test_match_exact_rejects_short_target():
    """A normalized target shorter than 4 chars never matches."""
    media = {"title": {"romaji": "abc", "english": "abc"}}
    assert anilist_mod._match_exact("abc", media) is False


def test_match_exact_matches_with_none_english():
    """A None english title does not break matching against romaji."""
    media = {"title": {"romaji": "Bleach", "english": None}}
    assert anilist_mod._match_exact("Bleach", media) is True


def test_match_exact_with_none_title_dict_returns_false():
    """media['title'] being None falls back to {} and returns False, no raise."""
    assert anilist_mod._match_exact("Bleach", {"title": None}) is False


def test_canon_saison1_returns_cached_without_fetch(monkeypatch):
    """A non-None disk cache short-circuits before any network fetch."""
    fake = _FakeDisk(get_value={"matched": True, "episodes": 12, "finished": True})
    monkeypatch.setattr(anilist_mod, "_disk", fake)
    monkeypatch.setattr(anilist_mod, "_ENABLED", True)

    def _boom(_titre):
        raise AssertionError("_fetch_sync must not be called on cache hit")

    monkeypatch.setattr(anilist_mod, "_fetch_sync", _boom)

    out = anilist_mod.canon_saison1("Bleach")
    assert out == {"matched": True, "episodes": 12, "finished": True}
    assert fake.set_calls == []


def test_canon_saison1_disabled_returns_none(monkeypatch):
    """When _ENABLED is False, no cache or fetch is touched and None is returned."""
    fake = _FakeDisk(get_value={"matched": True})
    monkeypatch.setattr(anilist_mod, "_disk", fake)
    monkeypatch.setattr(anilist_mod, "_ENABLED", False)

    def _boom(_titre):
        raise AssertionError("_fetch_sync must not be called when disabled")

    monkeypatch.setattr(anilist_mod, "_fetch_sync", _boom)

    assert anilist_mod.canon_saison1("Bleach") is None
    assert fake.get_calls == []


def test_canon_saison1_fresh_title_builds_and_caches(monkeypatch):
    """A cache miss fetches, builds a matched result and writes it to disk."""
    fake = _FakeDisk(get_value=None)
    monkeypatch.setattr(anilist_mod, "_disk", fake)
    monkeypatch.setattr(anilist_mod, "_ENABLED", True)

    media = {
        "title": {"romaji": "Bleach", "english": "Bleach"},
        "episodes": 366,
        "status": "FINISHED",
    }
    monkeypatch.setattr(anilist_mod, "_fetch_sync", lambda _t: media)

    out = anilist_mod.canon_saison1("Bleach")
    assert out == {"matched": True, "episodes": 366, "finished": True}
    assert fake.set_calls == [(anilist_mod._norm("Bleach"), out)]


def test_fetch_sync_returns_media_on_200(monkeypatch):
    """A 200 response yields data.Media unchanged."""
    media = {"id": 1, "title": {"romaji": "X"}}
    resp = _FakeResp(status_code=200, payload={"data": {"Media": media}})
    monkeypatch.setattr(anilist_mod.requests, "post", lambda *a, **k: resp)
    assert anilist_mod._fetch_sync("X") == media


def test_fetch_sync_non200_returns_none(monkeypatch):
    """A non-200 status returns None."""
    resp = _FakeResp(status_code=500, payload={"data": {"Media": {"id": 1}}})
    monkeypatch.setattr(anilist_mod.requests, "post", lambda *a, **k: resp)
    assert anilist_mod._fetch_sync("X") is None


def test_fetch_sync_swallows_exception(monkeypatch):
    """An exception from requests.post is caught and None is returned."""

    def _raise(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(anilist_mod.requests, "post", _raise)
    assert anilist_mod._fetch_sync("X") is None


@pytest.fixture(autouse=True)
def _reset_scan_cache():
    """Snapshot and restore the module-level scan info cache around each test."""
    with scan_mod._scan_info_lock:
        snapshot = dict(scan_mod._scan_info_cache)
        scan_mod._scan_info_cache.clear()
    yield
    with scan_mod._scan_info_lock:
        scan_mod._scan_info_cache.clear()
        scan_mod._scan_info_cache.update(snapshot)


def test_scan_info_set_keeps_all_when_not_overfull(monkeypatch):
    """At or below 200 entries every key is retained."""
    monkeypatch.setattr(scan_mod.time, "time", lambda: 1000.0)
    for i in range(150):
        scan_mod._scan_info_set(f"k{i}", {"v": i})
    assert len(scan_mod._scan_info_cache) == 150


def test_scan_info_set_clears_when_overfull_and_all_fresh(monkeypatch):
    """When >200 fresh entries exist, cleanup keeps >200 so clear() leaves only the newest."""
    monkeypatch.setattr(scan_mod.time, "time", lambda: 1000.0)
    for i in range(202):
        scan_mod._scan_info_set(f"k{i}", {"v": i})
    assert len(scan_mod._scan_info_cache) == 1
    assert "k201" in scan_mod._scan_info_cache
    assert scan_mod._scan_info_cache["k201"][1] == {"v": 201}


def test_get_scan_info_sync_disk_cache_hit(monkeypatch):
    """A disk-cache hit returns verbatim, primes the memory cache, and skips fetch."""
    cached = {"ok": True, "slug": "x", "oeuvre": "X", "lang": "vf",
              "langues": ["vf"], "chapitres": [{"num": "1", "pages": 5}], "total": 1}
    fake_disk = _FakeDisk(get_value=cached)
    monkeypatch.setattr(scan_mod, "_scan_disk", fake_disk)

    def _boom(*a, **k):
        raise AssertionError("_fetch_text must not run on disk-cache hit")

    monkeypatch.setattr(scan_mod, "_fetch_text", _boom)
    monkeypatch.setattr(scan_mod.time, "time", lambda: 5000.0)

    out = scan_mod.get_scan_info_sync("good-slug", "vf")
    assert out is cached
    assert scan_mod._scan_info_get("good-slug|vf") is cached


def test_fetch_api_retry_returns_none_after_all_failures(monkeypatch):
    """All-500 responses exhaust `tries` attempts and return None."""
    calls = {"n": 0}

    def fake_fetch(url, referer=None):
        calls["n"] += 1
        return 500, ""

    sleeps = []
    monkeypatch.setattr(scan_mod, "_fetch_text", fake_fetch)
    monkeypatch.setattr(scan_mod.time, "sleep", lambda s: sleeps.append(s))

    assert scan_mod._fetch_api_retry("u", tries=3) is None
    assert calls["n"] == 3
    assert sleeps == [0.6, 0.6]


def test_fetch_api_retry_stops_early_on_success(monkeypatch):
    """A 200 body on the second attempt returns it and stops without a trailing sleep."""
    scripted = [(500, ""), (200, "body")]
    calls = {"n": 0}

    def fake_fetch(url, referer=None):
        out = scripted[calls["n"]]
        calls["n"] += 1
        return out

    sleeps = []
    monkeypatch.setattr(scan_mod, "_fetch_text", fake_fetch)
    monkeypatch.setattr(scan_mod.time, "sleep", lambda s: sleeps.append(s))

    assert scan_mod._fetch_api_retry("u", tries=3) == "body"
    assert calls["n"] == 2
    assert sleeps == [0.6]


def test_fetch_text_truncates_and_closes(monkeypatch):
    """Chunks exceeding max_bytes are truncated, status is returned, response closed."""
    resp = _FakeStreamResp(status_code=200, chunks=[b"aaaa", b"bbbb", b"cccc"])
    session = _FakeSession(response=resp)
    monkeypatch.setattr(scan_mod, "_get_session", lambda _heads: session)

    warnings = []
    monkeypatch.setattr(scan_mod.log, "warning", lambda *a, **k: warnings.append(a))

    status, text = scan_mod._fetch_text("http://x/y", max_bytes=5)
    assert status == 200
    assert text == "aaaa"
    assert resp.closed == 1
    assert warnings


def test_fetch_text_session_get_raises_returns_minus_one(monkeypatch):
    """When session.get raises, (-1, '') is returned and the finally tolerates r=None."""
    session = _FakeSession(exc=RuntimeError("boom"))
    monkeypatch.setattr(scan_mod, "_get_session", lambda _heads: session)

    status, text = scan_mod._fetch_text("http://x/y")
    assert status == -1
    assert text == ""


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "—"),
        (-5, "—"),
        (45, "45s"),
        (125, "2m05s"),
        (3725, "1h02m05s"),
    ],
)
def test_fmt_duration(seconds, expected):
    """Duration formatting handles zero/negative, seconds, minutes and hours."""
    assert ls._fmt_duration(seconds) == expected


def test_shorten_name_keeps_last_segment_padded():
    """The last dotted segment is kept and left-justified to the width."""
    assert ls._shorten_name("engine.scraping.scan") == "scan".ljust(14)


def test_shorten_name_truncates_long_segment():
    """A segment longer than width is truncated to width-1 chars plus ellipsis."""
    out = ls._shorten_name("a" * 30, width=10)
    assert out == "a" * 9 + "…"
    assert len(out) == 10


def _record(msg, exc_info=None):
    rec = logging.LogRecord(
        name="asyncio",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    return rec


def test_noise_filter_passes_unrelated_message():
    """A record without the future-exception phrase passes through."""
    f = ls._AsyncioNoiseFilter()
    assert f.filter(_record("something totally normal")) is True


def test_noise_filter_drops_target_closed_phrase_in_message():
    """The future-exception phrase plus TargetClosedError text is dropped."""
    f = ls._AsyncioNoiseFilter()
    msg = "Future exception was never retrieved: TargetClosedError happened"
    assert f.filter(_record(msg)) is False


def test_noise_filter_drops_on_cancelled_exc_info():
    """A CancelledError in exc_info with the phrase is dropped via the mro walk."""
    f = ls._AsyncioNoiseFilter()
    import asyncio
    exc = asyncio.CancelledError()
    rec = _record("Future exception was never retrieved", exc_info=(type(exc), exc, None))
    assert f.filter(rec) is False


def test_noise_filter_passes_benign_future_exception():
    """The phrase with an unrelated benign exception/message still passes."""
    f = ls._AsyncioNoiseFilter()
    exc = ValueError("ordinary failure")
    rec = _record("Future exception was never retrieved", exc_info=(type(exc), exc, None))
    assert f.filter(rec) is True
