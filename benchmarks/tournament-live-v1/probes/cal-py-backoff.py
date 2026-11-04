"""Probe for cal-py-backoff, written from the task prompt only (before any candidate diff was read).
Prints, for each input, the repr of the result or the exception class (messages are not part of the spec)."""
from backoff import delays

CASES = [
    ((0,), {}), ((1,), {}), ((3, 1, 2, 100), {}), ((5, 1, 2, 10), {}), ((4, 2, 3, 2), {}),
    ((3, 0.5, 1.5, 10), {}), ((3, 1, 1, 1), {}), ((6, 1.0, 2.0, 60.0), {}), ((40,), {}),
    ((-1,), {}), ((2, 0), {}), ((2, -1), {}), ((2, 1, 0.5), {}), ((2, 5, 2, 4), {}),
    ((True,), {}), ((False,), {}), ((2.0,), {}), (("3",), {}), ((None,), {}),
    ((-1.5,), {}), ((True, 0), {}), ((2, 1, 2, float("inf")), {}),
    ((2,), {"base": 3, "cap": 3}), ((3,), {"factor": 1.0}),
]
for args, kwargs in CASES:
    try:
        out = repr(delays(*args, **kwargs))
    except Exception as exc:  # noqa: BLE001 - the probe records which exception class
        out = "raises " + type(exc).__name__
    print(f"delays{args}{kwargs or ''} -> {out}")
