import time

from engine.cache.ttl_cache import TTLCache


def test_set_get():
    c = TTLCache(100)
    assert c.get() is None
    c.set({"a": 1})
    assert c.get() == {"a": 1}

def test_set_empty_value_is_distinguished_from_miss():
    c = TTLCache(100)
    c.set([])
    assert c.get() == []

def test_invalidate():
    c = TTLCache(100)
    c.set(42)
    c.invalidate()
    assert c.get() is None

def test_expiry(monkeypatch):
    import engine.cache.ttl_cache as m
    c = TTLCache(10)
    c.set("v")
    future = time.time() + 11
    monkeypatch.setattr(m.time, "time", lambda: future)
    assert c.get() is None
