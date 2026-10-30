from ttlcache import TTLCache


def test_get_returns_fresh_value():
    c = TTLCache(10)
    c.set("k", "v", now=100)
    assert c.get("k", now=105) == "v"


def test_missing_key_returns_default():
    assert TTLCache(10).get("nope", now=0, default="d") == "d"


def test_entry_expires_exactly_at_ttl():
    c = TTLCache(10)
    c.set("k", "v", now=100)
    assert c.get("k", now=110) is None


def test_just_before_ttl_is_still_valid():
    c = TTLCache(10)
    c.set("k", "v", now=100)
    assert c.get("k", now=109.5) == "v"
