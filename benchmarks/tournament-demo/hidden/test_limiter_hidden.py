import tracemalloc

from limiter import RateLimiter


def test_sliding_window_expiry_is_exact():
    r = RateLimiter(2, 10)
    assert r.allow("a", 8) and r.allow("a", 9)
    assert not r.allow("a", 17.5)        # both events still inside the window
    assert r.allow("a", 18.0)            # the event at t=8 is no longer counted (now < t + window is false)
    assert not r.allow("a", 18.5)        # events at 9 and 18 are inside


def test_denied_requests_do_not_consume_capacity():
    r = RateLimiter(1, 10)
    assert r.allow("a", 0)
    for t in (1, 2, 3, 4, 5):
        assert not r.allow("a", t)
    assert r.allow("a", 10.0)


def test_pending_counts_allowed_events_inside_the_window():
    r = RateLimiter(3, 10)
    assert r.pending("never-seen") == 0
    for t in (0, 1, 2):
        assert r.allow("a", t)
    assert r.pending("a") == 3
    assert r.allow("a", 10.5)            # t=0 has expired; 1, 2 and 10.5 are inside
    assert r.pending("a") == 3
    assert r.allow("b", 0)               # separate key
    assert r.pending("b") == 1


def test_memory_per_key_is_bounded_by_limit():
    r = RateLimiter(3, 10)
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        for i in range(60000):
            r.allow("a", i * 0.001)       # 60 s of traffic, only 3 allowed per 10 s
        grown = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    assert grown < 20_000, grown


def test_constructor_validation_is_preserved():
    for args in ((0, 1), (1, 0), (-1, 5)):
        try:
            RateLimiter(*args)
        except ValueError:
            continue
        raise AssertionError(args)
