from limiter import RateLimiter


def test_blocks_after_limit_within_window():
    r = RateLimiter(2, 10)
    assert [r.allow("a", t) for t in (0, 1, 2)] == [True, True, False]


def test_keys_are_independent():
    r = RateLimiter(1, 10)
    assert r.allow("a", 0) and r.allow("b", 0)
    assert not r.allow("a", 1)


def test_allows_again_after_window_passes():
    r = RateLimiter(1, 10)
    assert r.allow("a", 0)
    assert r.allow("a", 25)


def test_no_burst_across_a_window_boundary():
    r = RateLimiter(2, 10)
    assert r.allow("a", 8) and r.allow("a", 9)
    assert not r.allow("a", 11)
