import time

from engine.scraping._cache import EP_CACHE_MAX, ScraperCache


def test_fav_set_get_and_freshness():
    c = ScraperCache()
    assert c.fav_fresh() is False
    c.set_fav([{"nom": "A"}])
    assert c.fav_fresh() is True
    assert c.get_fav() == [{"nom": "A"}]

def test_fav_get_returns_copy():
    c = ScraperCache()
    c.set_fav([{"nom": "A"}])
    out = c.get_fav()
    out.append({"nom": "B"})
    assert len(c.get_fav()) == 1

def test_fav_invalidate():
    c = ScraperCache()
    c.set_fav([1, 2, 3])
    c.invalidate_fav()
    assert c.fav_fresh() is False
    assert c.get_fav() == []

def test_ep_set_get():
    c = ScraperCache()
    c.set_ep("k", {"total": 5})
    assert c.get_ep("k") == {"total": 5}
    assert c.get_ep("absent") is None

def test_ep_ttl_expiry(monkeypatch):
    import engine.scraping._cache as m
    c = ScraperCache()
    c.set_ep("k", {"x": 1})
    future = time.time() + m.EP_CACHE_TTL + 1
    monkeypatch.setattr(m.time, "time", lambda: future)
    assert c.get_ep("k") is None

def test_ep_invalidate_one_and_all():
    c = ScraperCache()
    c.set_ep("a", {})
    c.set_ep("b", {})
    c.invalidate_ep("a")
    assert c.get_ep("a") is None
    assert c.get_ep("b") == {}
    c.invalidate_ep()
    assert c.get_ep("b") is None

def test_ep_max_eviction():
    c = ScraperCache()
    for i in range(EP_CACHE_MAX + 5):
        c.set_ep(f"k{i}", {"i": i})
    assert len(c._ep) <= EP_CACHE_MAX
