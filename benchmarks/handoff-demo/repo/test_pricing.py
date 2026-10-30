from pricing import apply_discount


def test_discount_whole():
    assert apply_discount(1000, 10) == 900


def test_discount_rounds_half_up():
    assert apply_discount(1005, 50) == 503  # 502.5 -> 503


def test_discount_rounds_down_below_half():
    assert apply_discount(999, 10) == 899  # 899.1 -> 899
