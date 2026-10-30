from ttlcache import TTLCache


def test_set_on_existing_key_overwrites_value_and_refreshes_ttl():
    c = TTLCache(10)
    c.set("k", "old", now=100)
    c.set("k", "new", now=108)
    assert c.get("k", now=115) == "new"
    assert c.get("k", now=118) is None


def test_purge_removes_expired_and_reports_count():
    c = TTLCache(10)
    c.set("a", 1, now=0)
    c.set("b", 2, now=5)
    c.set("c", 3, now=9)
    assert c.purge(now=10) == 1
    assert len(c) == 2
    assert c.get("a", now=10) is None
    assert c.get("b", now=10) == 2
