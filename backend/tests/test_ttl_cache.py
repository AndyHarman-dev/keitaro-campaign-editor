from app.api.deps import TtlCache


def test_value_expires_after_its_ttl():
    now = [0.0]
    cache = TtlCache(60, clock=lambda: now[0])
    assert cache.get() is None
    cache.put(["a"])
    now[0] = 60
    assert cache.get() == ["a"]
    now[0] = 60.5
    assert cache.get() is None


def test_clear_forgets_the_value():
    cache = TtlCache(60, clock=lambda: 0.0)
    cache.put(["a"])
    cache.clear()
    assert cache.get() is None
