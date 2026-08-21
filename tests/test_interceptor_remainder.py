import asyncio
import logging

import pytest

import engine.download.interceptor as ic


async def _anoop(*args, **kwargs):
    return None


def _snapshot_globals():
    return {
        "sem": ic._ctx_semaphore_state["sem"],
        "sem_loop": ic._ctx_semaphore_state["loop"],
        "lock": ic._browser_lock_state["lock"],
        "lock_loop": ic._browser_lock_state["loop"],
        "browser": ic._browser,
        "playwright": ic._playwright,
        "default_handler": ic._default_exception_handler,
        "installed": set(ic._handler_installed_on_loop),
    }


def _restore_globals(snap):
    ic._ctx_semaphore_state["sem"] = snap["sem"]
    ic._ctx_semaphore_state["loop"] = snap["sem_loop"]
    ic._browser_lock_state["lock"] = snap["lock"]
    ic._browser_lock_state["loop"] = snap["lock_loop"]
    ic._browser = snap["browser"]
    ic._playwright = snap["playwright"]
    ic._default_exception_handler = snap["default_handler"]
    ic._handler_installed_on_loop.clear()
    for loop in snap["installed"]:
        ic._handler_installed_on_loop.add(loop)


@pytest.fixture(autouse=True)
def _isolate_globals():
    snap = _snapshot_globals()
    ic._ctx_semaphore_state["sem"] = None
    ic._ctx_semaphore_state["loop"] = None
    ic._browser_lock_state["lock"] = None
    ic._browser_lock_state["loop"] = None
    ic._browser = None
    ic._playwright = None
    ic._default_exception_handler = None
    ic._handler_installed_on_loop.clear()
    yield
    _restore_globals(snap)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(ic.asyncio, "sleep", _anoop)
    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _anoop)
    monkeypatch.setattr(ic, "_install_loop_exception_handler", lambda: None)


def test_est_url_http_accepts_http_and_https():
    assert ic._est_url_http("http://host/embed") is True
    assert ic._est_url_http("https://host/embed") is True


def test_est_url_http_rejects_non_http_and_non_str():
    assert ic._est_url_http("ftp://host/file") is False
    assert ic._est_url_http("") is False
    assert ic._est_url_http(None) is False


def test_parallele_first_dict_wins_and_pending_cancelled(monkeypatch):
    calls = []
    cancelled = []

    async def _stub(src, timeout=8, _in_parallel=False):
        calls.append(src)
        if src == "http://winner":
            return {"url": "http://winner/master.m3u8", "headers": {"w": "1"}}
        fut = asyncio.get_running_loop().create_future()
        try:
            await fut
        except asyncio.CancelledError:
            cancelled.append(src)
            raise

    monkeypatch.setattr(ic, "intercepter_lecteur", _stub)

    lecteurs = [
        {"src": "http://loser1"},
        {"src": "http://winner"},
        {"src": "http://loser2"},
    ]
    result = asyncio.run(ic.intercepter_lecteurs_parallele(lecteurs, timeout=2))

    assert result == {"url": "http://winner/master.m3u8", "headers": {"w": "1"}}
    assert "http://winner" in calls
    assert set(cancelled) == {"http://loser1", "http://loser2"}


def test_parallele_skips_none_results_until_dict(monkeypatch):
    calls = []

    async def _stub(src, timeout=8, _in_parallel=False):
        calls.append(src)
        if src == "http://hit":
            return {"url": "http://hit/x.m3u8", "headers": {}}
        return None

    monkeypatch.setattr(ic, "intercepter_lecteur", _stub)

    lecteurs = [
        {"src": "http://miss1"},
        {"src": "http://miss2"},
        {"src": "http://hit"},
    ]
    result = asyncio.run(ic.intercepter_lecteurs_parallele(lecteurs, timeout=2))

    assert result == {"url": "http://hit/x.m3u8", "headers": {}}
    assert set(calls) == {"http://miss1", "http://miss2", "http://hit"}


def test_parallele_all_fail_logs_warning_and_returns_none(monkeypatch, caplog):
    seen = []

    async def _stub(src, timeout=8, _in_parallel=False):
        seen.append(src)
        raise RuntimeError(f"boom-{src}")

    monkeypatch.setattr(ic, "intercepter_lecteur", _stub)

    lecteurs = [{"src": "http://a"}, {"src": "http://b"}]
    with caplog.at_level(logging.WARNING, logger="engine.download.interceptor"):
        result = asyncio.run(ic.intercepter_lecteurs_parallele(lecteurs, timeout=2))

    assert result is None
    assert set(seen) == {"http://a", "http://b"}
    assert any("tous les lecteurs ont échoué" in rec.message for rec in caplog.records)


def test_parallele_all_none_resets_browser(monkeypatch):
    reset_calls = []

    async def _recorder():
        reset_calls.append(True)

    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _recorder)

    async def _stub(src, timeout=8, _in_parallel=False):
        return None

    monkeypatch.setattr(ic, "intercepter_lecteur", _stub)

    result = asyncio.run(ic.intercepter_lecteurs_parallele([{"src": "http://a"}], timeout=2))

    assert result is None
    assert reset_calls == [True]


def test_parallele_success_does_not_reset_browser(monkeypatch):
    reset_calls = []

    async def _recorder():
        reset_calls.append(True)

    monkeypatch.setattr(ic, "_reset_browser_apres_erreur", _recorder)

    async def _stub(src, timeout=8, _in_parallel=False):
        return {"url": "http://a/x.m3u8", "headers": {}}

    monkeypatch.setattr(ic, "intercepter_lecteur", _stub)

    result = asyncio.run(ic.intercepter_lecteurs_parallele([{"src": "http://a"}], timeout=2))

    assert result == {"url": "http://a/x.m3u8", "headers": {}}
    assert reset_calls == []


def test_parallele_filters_non_dict_and_missing_src(monkeypatch):
    calls = []

    async def _stub(src, timeout=8, _in_parallel=False):
        calls.append(src)
        return {"url": src + "/x.m3u8", "headers": {}}

    monkeypatch.setattr(ic, "intercepter_lecteur", _stub)

    lecteurs = [
        {"src": "http://keep"},
        "not-a-dict",
        {"nosrc": 1},
        123,
        {"src": ""},
    ]
    result = asyncio.run(ic.intercepter_lecteurs_parallele(lecteurs, timeout=2))

    assert calls == ["http://keep"]
    assert result == {"url": "http://keep/x.m3u8", "headers": {}}


def test_parallele_no_exploitable_returns_none(monkeypatch, caplog):
    async def _stub(src, timeout=8, _in_parallel=False):
        raise AssertionError("should not be called")

    monkeypatch.setattr(ic, "intercepter_lecteur", _stub)

    lecteurs = ["nope", {"nosrc": 1}, {"src": ""}]
    with caplog.at_level(logging.WARNING, logger="engine.download.interceptor"):
        result = asyncio.run(ic.intercepter_lecteurs_parallele(lecteurs, timeout=2))

    assert result is None
    assert any("Aucun lecteur exploitable" in rec.message for rec in caplog.records)


def test_parallele_truncates_to_max(monkeypatch):
    calls = []

    async def _stub(src, timeout=8, _in_parallel=False):
        calls.append(src)
        return None

    monkeypatch.setattr(ic, "intercepter_lecteur", _stub)

    n = ic.MAX_LECTEURS_PARALLELES + 2
    srcs = [f"http://src{i}" for i in range(n)]
    lecteurs = [{"src": s} for s in srcs]

    result = asyncio.run(ic.intercepter_lecteurs_parallele(lecteurs, timeout=2))

    assert result is None
    assert len(calls) == ic.MAX_LECTEURS_PARALLELES
    assert set(calls) == set(srcs[: ic.MAX_LECTEURS_PARALLELES])


def test_ctx_semaphore_same_loop_returns_same_object():
    async def _run():
        a = ic._ctx_semaphore()
        b = ic._ctx_semaphore()
        return a, b

    a, b = asyncio.run(_run())
    assert isinstance(a, asyncio.Semaphore)
    assert a is b


def test_ctx_semaphore_new_loop_recreates():
    first = asyncio.run(_return_ctx_semaphore())
    second = asyncio.run(_return_ctx_semaphore())
    assert first is not second


async def _return_ctx_semaphore():
    return ic._ctx_semaphore()


def test_browser_lock_same_loop_returns_same_object():
    async def _run():
        a = ic._browser_lock()
        b = ic._browser_lock()
        return a, b

    a, b = asyncio.run(_run())
    assert isinstance(a, asyncio.Lock)
    assert a is b


def test_browser_lock_new_loop_recreates():
    first = asyncio.run(_return_browser_lock())
    second = asyncio.run(_return_browser_lock())
    assert first is not second


async def _return_browser_lock():
    return ic._browser_lock()


def test_install_loop_exception_handler_installs_custom(monkeypatch):
    monkeypatch.undo()
    sentinel = lambda loop, context: None
    captured = {}

    async def _run():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(sentinel)
        ic._install_loop_exception_handler()
        captured["active"] = loop.get_exception_handler()
        captured["default"] = ic._default_exception_handler
        captured["registered"] = loop in ic._handler_installed_on_loop

    asyncio.run(_run())

    assert captured["active"] is ic._custom_exception_handler
    assert captured["default"] is sentinel
    assert captured["registered"] is True


def test_install_loop_exception_handler_idempotent(monkeypatch):
    monkeypatch.undo()
    marker = object()
    captured = {}

    async def _run():
        ic._install_loop_exception_handler()
        ic._default_exception_handler = marker
        ic._install_loop_exception_handler()
        captured["default_after_second"] = ic._default_exception_handler

    asyncio.run(_run())

    assert captured["default_after_second"] is marker


def test_custom_handler_delegates_real_context(monkeypatch):
    seen = []
    monkeypatch.setattr(ic, "_default_exception_handler", lambda ctx: seen.append(ctx))

    ctx = {"message": "real failure", "exception": ValueError("nope")}
    ic._custom_exception_handler(object(), ctx)

    assert seen == [ctx]


def test_custom_handler_suppresses_noise_message(monkeypatch):
    seen = []
    monkeypatch.setattr(ic, "_default_exception_handler", lambda ctx: seen.append(ctx))

    ic._custom_exception_handler(object(), {"message": "Target page, context or browser has been closed"})

    assert seen == []


def test_custom_handler_suppresses_noise_exception(monkeypatch):
    seen = []
    monkeypatch.setattr(ic, "_default_exception_handler", lambda ctx: seen.append(ctx))

    ic._custom_exception_handler(object(), {"exception": asyncio.CancelledError()})

    assert seen == []


def test_custom_handler_logs_when_no_default(monkeypatch, caplog):
    monkeypatch.setattr(ic, "_default_exception_handler", None)

    with caplog.at_level(logging.ERROR, logger="engine.download.interceptor"):
        ic._custom_exception_handler(object(), {"message": "real", "exception": ValueError("x")})

    assert any(rec.levelno == logging.ERROR for rec in caplog.records)


def test_custom_handler_delegates_via_two_arg_fallback(monkeypatch):
    seen = []
    monkeypatch.setattr(ic, "_default_exception_handler", lambda loop, context: seen.append(context))

    ctx = {"message": "real failure two-arg"}
    sentinel_loop = object()
    ic._custom_exception_handler(sentinel_loop, ctx)

    assert seen == [ctx]
