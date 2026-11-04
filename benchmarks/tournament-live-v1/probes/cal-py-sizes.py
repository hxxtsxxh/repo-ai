"""Probe for cal-py-sizes, written from the task prompt only (before any candidate diff was read).
Prints, for each input, the repr of the result or the exception class (messages are not part of the spec)."""
from sizes import parse_size

CASES = ["7", "0", "10KB", "10kb", "10 KB", "2GB", "5b", "1KiB", "1kib", "1.5KiB", "0.5KB", "1gib", "3MiB",
         "1.3B", "0.1KiB", "1.0B", "1.25KB", "10.KB", ".5KB", "1e3", "10  KB", " 10KB", "10KB ", "10\tKB",
         "10 ", "", "KB", "-1", "1XB", "+1", "1_000", "١٠", "10Kb", "10 kib", "0.000KB", "007", "1.5",
         "99999999999999999999GiB", "1.0000000001KiB", "10K", "10 B"]
for text in CASES:
    try:
        out = repr(parse_size(text))
    except Exception as exc:  # noqa: BLE001 - the probe records which exception class
        out = "raises " + type(exc).__name__
    print(f"parse_size({text!r}) -> {out}")
for bad in (10, None, b"10KB", 1.5):
    try:
        out = repr(parse_size(bad))
    except Exception as exc:  # noqa: BLE001
        out = "raises " + type(exc).__name__
    print(f"parse_size({bad!r}) -> {out}")
