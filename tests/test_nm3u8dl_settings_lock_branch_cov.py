import threading

import pytest

import engine.config.user_settings as user_settings
import engine.download.methods.nm3u8dl as nm3u8dl


@pytest.fixture(autouse=True)
def _snapshot_settings_cache():
    lock = nm3u8dl._settings_cache_lock
    with lock:
        cache_snap = nm3u8dl._settings_cache
        ts_snap = nm3u8dl._settings_cache_ts
        nm3u8dl._settings_cache = None
        nm3u8dl._settings_cache_ts = 0.0
    yield
    with lock:
        nm3u8dl._settings_cache = cache_snap
        nm3u8dl._settings_cache_ts = ts_snap


def test_get_user_settings_releases_lock_during_disk_read(monkeypatch):
    observed = {}

    def _probing_load():
        acquired = nm3u8dl._settings_cache_lock.acquire(blocking=False)
        observed["lock_free_during_load"] = acquired
        if acquired:
            nm3u8dl._settings_cache_lock.release()
        return {"qualite": "720", "thread_count": 4}

    monkeypatch.setattr(user_settings, "load_settings", _probing_load)

    res = nm3u8dl._get_user_settings()

    assert observed["lock_free_during_load"] is True
    assert res == {"qualite": "720", "thread_count": 4}
    assert nm3u8dl._settings_cache == {"qualite": "720", "thread_count": 4}


def test_get_user_settings_cache_hit_after_release_does_not_reload(monkeypatch):
    monkeypatch.setattr(
        user_settings, "load_settings", lambda: {"qualite": "1080", "thread_count": 8}
    )
    first = nm3u8dl._get_user_settings()
    assert first == {"qualite": "1080", "thread_count": 8}

    def _boom():
        raise AssertionError("cache hit must not reload")

    monkeypatch.setattr(user_settings, "load_settings", _boom)
    second = nm3u8dl._get_user_settings()
    assert second == {"qualite": "1080", "thread_count": 8}
    assert second is not first


def test_get_user_settings_non_dict_falls_back_outside_lock(monkeypatch):
    monkeypatch.setattr(user_settings, "load_settings", lambda: ["x"])
    res = nm3u8dl._get_user_settings()
    assert res == {"qualite": "auto", "thread_count": 16, "downloads_dir": ""}
    assert nm3u8dl._settings_cache is None


def test_get_user_settings_exception_falls_back_outside_lock(monkeypatch):
    def _boom():
        raise RuntimeError("unreadable")

    monkeypatch.setattr(user_settings, "load_settings", _boom)
    res = nm3u8dl._get_user_settings()
    assert res == {"qualite": "auto", "thread_count": 16, "downloads_dir": ""}
    assert nm3u8dl._settings_cache is None


def test_get_user_settings_concurrent_miss_loads_are_idempotent(monkeypatch):
    def _load():
        return {"qualite": "auto", "thread_count": 16, "downloads_dir": ""}

    monkeypatch.setattr(user_settings, "load_settings", _load)

    barrier = threading.Barrier(8)
    out: list = []

    def _worker():
        barrier.wait()
        out.append(nm3u8dl._get_user_settings())

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = {"qualite": "auto", "thread_count": 16, "downloads_dir": ""}
    assert all(o == expected for o in out)
    assert len({id(o) for o in out}) == len(out)
