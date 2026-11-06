"""Probe for cal-py-backoff: delays(attempts, base=1.0, factor=2.0, cap=60.0)."""
from fractions import Fraction
from decimal import Decimal

from backoff import delays


class MyInt(int):
    pass


def show(label, args, kwargs=None, summarize=False):
    kwargs = kwargs or {}
    try:
        r = delays(*args, **kwargs)
        if summarize:
            lst = list(r)
            out = "type=%s len=%d head=%r tail=%r types=%s" % (
                type(r).__name__, len(lst), lst[:3], lst[-3:],
                sorted({type(x).__name__ for x in lst}))
        else:
            try:
                types = sorted({type(x).__name__ for x in r})
            except Exception:
                types = "?"
            out = "%s %r types=%s" % (type(r).__name__, r, types)
    except Exception as e:  # noqa: BLE001
        out = "EXC " + type(e).__name__
    print("%s | args=%r kwargs=%r -> %s" % (label, args, kwargs, out))


# R1 / R4 basic schedules
show("r4-example", (3, 1, 2, 100))
show("defaults-5", (5,))
show("defaults-8-caps", (8,))
show("defaults-1", (1,))
show("int-cap-hit", (5, 1, 2, 5))
show("int-cap-exact", (4, 1, 2, 8))
show("float-cap-mixed", (4, 1, 2, 3.5))
show("base-gt1", (4, 3, 3, 50))
show("factor-1", (3, 5, 1, 5))
show("factor-1-cap-gt", (3, 2, 1, 10))
show("cap-eq-base", (3, 2, 2, 2))
show("frac-base", (3, 0.5, 2, 1))
show("fraction-args", (3, Fraction(1, 3), Fraction(3, 2), Fraction(2)))
show("decimal-args", (3, Decimal("0.1"), Decimal("2"), Decimal("1")))
show("cap-inf", (4,), {"cap": float("inf")})
show("factor-float-1.5", (5, 1, 1.5, 3))
# R2
show("zero", (0,))
show("zero-int-args", (0, 1, 2, 100))
show("neg1", (-1,))
show("neg-large", (-10 ** 20,))
# R3 validation
show("base-0", (3, 0))
show("base-neg", (3, -1))
show("factor-lt1", (3, 1, 0.5))
show("factor-0", (3, 1, 0))
show("cap-lt-base", (3, 2, 2, 1))
show("cap-0", (3, 1, 2, 0))
show("base-nan", (3, float("nan")))
show("factor-nan", (3, 1, float("nan")))
show("cap-nan", (3, 1, 2, float("nan")))
show("base-inf", (3, float("inf"), 2, float("inf")))
show("zero-attempts-bad-base", (0, 0))
show("zero-attempts-bad-factor", (0, 1, 0.5))
show("zero-attempts-bad-cap", (0, 5, 2, 1))
show("neg-attempts-bad-base", (-1, 0))
show("base-str", (3, "1"))
show("factor-str", (3, 1, "2"))
show("cap-none", (3, 1, 2, None))
show("base-bool", (3, True, 2, 10))
# R5 type checks and ordering
show("bool-true", (True,))
show("bool-false", (False,))
show("float-2.0", (2.0,))
show("str-3", ("3",))
show("none", (None,))
show("float-neg", (-1.0,))
show("float-bad-base", (2.0, 0))
show("bool-bad-base", (True, -1))
show("str-bad-cap", ("3", 1, 2, 0))
show("int-subclass", (MyInt(3), 1, 2, 100))
show("fraction-attempts", (Fraction(3),))
show("decimal-attempts", (Decimal(3),))
show("complex-attempts", (3 + 0j,))
show("kw-attempts", (), {"attempts": 2, "base": 1, "factor": 3, "cap": 100})
# very large: overflow / performance behaviour
show("large-int-args", (2000, 1, 2, 60), summarize=True)
show("large-float-default", (1100,), summarize=True)
show("large-float-factor-10", (400, 1.0, 10.0, 1e9), summarize=True)
