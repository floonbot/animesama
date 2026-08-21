import asyncio

import pytest

import engine.download.extractor.browser_extractor as be
import engine.download.interceptor as ic

SECURE_M3U8 = "https://cdn.example.com/secure/1/master.m3u8?token=abc"
PLAIN_HLS = "https://cdn.example.com/hls/video.m3u8"
JSON_M3U8 = "https://cdn.example.com/json/master.m3u8?k=1"
RAW_M3U8 = "https://cdn.example.com/raw/master.m3u8"

_LOGS_JS = "window.__STREAM_LOGS__ || []"


@pytest.fixture(autouse=True)
def _clear_js_hooks_cache():
    be.clear_js_hooks_cache()
    yield
    be.clear_js_hooks_cache()


def test_charger_js_hooks_memoized_reads_disk_once(monkeypatch):
    calls = {"n": 0}

    def counting_read(self, *a, **k):
        calls["n"] += 1
        return "JSHOOKSCONTENT"

    monkeypatch.setattr(type(be._JS_HOOKS_PATH), "read_text", counting_read)

    first = be._charger_js_hooks()
    second = be._charger_js_hooks()

    assert first == second == "JSHOOKSCONTENT"
    assert calls["n"] == 1


class FakeFrame:
    def __init__(self, url, evaluate_impl):
        self.url = url
        self._evaluate_impl = evaluate_impl
        self.evaluate_calls = []

    async def evaluate(self, js):
        self.evaluate_calls.append(js)
        return await self._evaluate_impl(js)


class FakePage:
    def __init__(
        self,
        cdp=None,
        content_html="",
        content_raises=None,
        stream_logs=None,
        shadow_urls=None,
        child_frames=None,
        goto_raises=None,
    ):
        self._cdp = cdp
        self._content_html = content_html
        self._content_raises = content_raises
        self._stream_logs = [] if stream_logs is None else stream_logs
        self._shadow_urls = [] if shadow_urls is None else shadow_urls
        self._child_frames = list(child_frames or [])
        self._goto_raises = goto_raises
        self._handlers = {}
        self.main_frame = self
        self.url = "http://host/main"
        self.closed = False
        self.goto_calls = []
        self.click_calls = []
        self.evaluate_calls = []

    @property
    def frames(self):
        return [self.main_frame, *self._child_frames]

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    async def goto(self, *args, **kwargs):
        self.goto_calls.append(kwargs)
        if self._goto_raises is not None:
            raise self._goto_raises
        if self._cdp is not None:
            self._cdp.fire_all()

    async def click(self, selector, timeout=None):
        self.click_calls.append((selector, timeout))
        raise RuntimeError("no play button")

    async def content(self):
        if self._content_raises is not None:
            raise self._content_raises
        return self._content_html

    async def evaluate(self, js):
        self.evaluate_calls.append(js)
        if js == _LOGS_JS:
            return self._stream_logs
        if "scanShadow" in js:
            return self._shadow_urls
        return []

    async def close(self):
        self.closed = True


class FakeCdp:
    def __init__(self, events=None):
        self._events = events or []
        self._handlers = {}
        self.sent = []
        self.detached = False

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    def fire_all(self):
        for event, params in self._events:
            for handler in self._handlers.get(event, []):
                handler(params)

    async def detach(self):
        self.detached = True


class FakeCtx:
    def __init__(self, page):
        self._page = page
        self.closed = False
        self.init_scripts = []

    async def new_page(self):
        return self._page

    async def add_init_script(self, js):
        self.init_scripts.append(js)

    async def new_cdp_session(self, page):
        return self._page._cdp

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page, new_context_raises=None):
        self._page = page
        self._new_context_raises = new_context_raises
        self.contexts = []

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        if self._new_context_raises is not None:
            raise self._new_context_raises
        ctx = FakeCtx(self._page)
        self.contexts.append(ctx)
        return ctx


async def _anoop(*args, **kwargs):
    return None


def _reset_interceptor_globals():
    ic._ctx_semaphore_state["sem"] = None
    ic._ctx_semaphore_state["loop"] = None
    ic._browser = None
    ic._playwright = None


@pytest.fixture(autouse=True)
def _isolate_globals():
    _reset_interceptor_globals()
    yield
    _reset_interceptor_globals()


def _patch_extractor(monkeypatch, browser, reset_recorder=None):
    async def _fake_get_browser():
        return browser

    monkeypatch.setattr(ic, "get_browser", _fake_get_browser)
    monkeypatch.setattr(ic, "apply_stealth", _anoop)
    monkeypatch.setattr(be.asyncio, "sleep", _anoop)
    if reset_recorder is None:
        monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)
    else:
        async def _record_reset(*args, **kwargs):
            reset_recorder.append(True)

        monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _record_reset)


def test_charger_js_hooks_reads_real_file_non_empty():
    contenu = be._charger_js_hooks()

    assert isinstance(contenu, str)
    assert contenu != ""
    assert len(contenu) > 100


def test_charger_js_hooks_missing_path_returns_empty_and_warns(monkeypatch, tmp_path, caplog):
    manquant = tmp_path / "does_not_exist" / "js_hooks.js"
    monkeypatch.setattr(be, "_JS_HOOKS_PATH", manquant)

    with caplog.at_level("WARNING", logger="engine.download.extractor.browser_extractor"):
        contenu = be._charger_js_hooks()

    assert contenu == ""
    assert any("js_hooks.js" in rec.message for rec in caplog.records)


def test_normaliser_strips_fragment():
    assert be._normaliser("https://h/x.m3u8#frag") == "https://h/x.m3u8"
    assert be._normaliser("https://h/p?q=1#anchor") == "https://h/p?q=1"


def test_normaliser_bad_input_returns_input_unchanged():
    sentinel = 123
    assert be._normaliser(sentinel) is sentinel


def test_score_url_secure_additive_alone():
    assert be._score_url("https://h/secure/1/file.bin", "x") == be._SCORE_SECURE


def test_score_url_perf_type_additive_alone():
    assert be._score_url("https://h/whatever", "perf_resource") == be._SCORE_PERF


def test_score_url_hlsjs_loadsource_additive_alone():
    assert be._score_url("https://h/whatever", "hlsjs_loadSource") == be._SCORE_HLSJS


def test_score_url_additive_sum_of_multiple_contributions():
    expected = (
        be._SCORE_M3U8
        + be._SCORE_MASTER
        + be._SCORE_SECURE
        + be._SCORE_PERF
    )
    assert be._score_url("https://cdn/secure/1/master.m3u8", "perf_resource") == expected


def test_meilleur_resultat_empty_is_none():
    assert be._meilleur_resultat([]) is None


def test_meilleur_resultat_single_returns_that_entry():
    only = {"url": "https://h/a.m3u8", "type": "cdp_response"}
    assert be._meilleur_resultat([only]) is only


def test_meilleur_resultat_tie_keeps_stable_first():
    a = {"url": "https://h/one.m3u8", "type": "fetch"}
    b = {"url": "https://h/two.m3u8", "type": "fetch"}
    assert be._meilleur_resultat([a, b]) is a


def test_forensic_scan_extracts_from_json_quoted_string():
    html = f'<script>var c = {{"file":"{JSON_M3U8}"}};</script>'
    page = FakePage(content_html=html)

    resultats = asyncio.run(be._forensic_scan(page))

    types = {r["type"] for r in resultats}
    assert "forensic_json" in types
    json_urls = {r["url"] for r in resultats if r["type"] == "forensic_json"}
    assert JSON_M3U8 in json_urls


def test_forensic_scan_strips_trailing_slash_and_backslash():
    html = f'fragment {RAW_M3U8}\\/ end'
    page = FakePage(content_html=html)

    resultats = asyncio.run(be._forensic_scan(page))

    html_entries = [r for r in resultats if r["type"] == "forensic_html"]
    assert html_entries
    assert all(not r["url"].endswith(("\\", "/")) for r in html_entries)
    assert html_entries[0]["url"] == RAW_M3U8


def test_forensic_scan_content_exception_returns_empty():
    page = FakePage(content_raises=RuntimeError("content boom"))

    assert asyncio.run(be._forensic_scan(page)) == []


def test_injecter_hooks_frame_swallows_evaluate_exception():
    async def _raise(js):
        raise RuntimeError("frame eval boom")

    frame = FakeFrame("http://host/childframe/long", _raise)

    asyncio.run(be._injecter_hooks_frame(frame, "console.log(1)"))

    assert frame.evaluate_calls == ["console.log(1)"]


def test_lire_logs_frame_non_list_returns_empty():
    async def _non_list(js):
        return {"not": "a list"}

    frame = FakeFrame("http://host/f", _non_list)

    assert asyncio.run(be._lire_logs_frame(frame)) == []
    assert frame.evaluate_calls == [_LOGS_JS]


def test_lire_logs_frame_list_passes_through():
    payload = [{"url": "https://h/a.m3u8", "type": "js"}]

    async def _list(js):
        return payload

    frame = FakeFrame("http://host/f", _list)

    assert asyncio.run(be._lire_logs_frame(frame)) == payload


def test_lire_logs_frame_evaluate_exception_returns_empty():
    async def _raise(js):
        raise RuntimeError("logs boom")

    frame = FakeFrame("http://host/f/deep", _raise)

    assert asyncio.run(be._lire_logs_frame(frame)) == []


def test_extraire_flux_invalid_url_early_return_no_goto(monkeypatch):
    page = FakePage(cdp=FakeCdp())
    _patch_extractor(monkeypatch, FakeBrowser(page))

    result = asyncio.run(be.extraire_flux("ftp://nope/here", timeout=3, mode="standard"))

    assert result == {"best": None, "all": [], "timeline": []}
    assert page.goto_calls == []
    assert page.closed is False


def test_extraire_flux_grave_error_triggers_browser_reset(monkeypatch):
    reset_calls = []
    page = FakePage(cdp=FakeCdp(events=[]))
    browser = FakeBrowser(
        page,
        new_context_raises=RuntimeError("Target page, context or browser has been closed"),
    )
    _patch_extractor(monkeypatch, browser, reset_recorder=reset_calls)

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="standard"))

    assert result == {"best": None, "all": [], "timeline": []}
    assert reset_calls == [True]


def test_extraire_flux_benign_error_does_not_reset_browser(monkeypatch):
    reset_calls = []
    page = FakePage(cdp=FakeCdp(events=[]))
    browser = FakeBrowser(page, new_context_raises=RuntimeError("some benign failure"))
    _patch_extractor(monkeypatch, browser, reset_recorder=reset_calls)

    result = asyncio.run(be.extraire_flux("http://host/embed", timeout=3, mode="standard"))

    assert result == {"best": None, "all": [], "timeline": []}
    assert reset_calls == []
