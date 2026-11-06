"""Probe for cal-py-sizes: parse_size(text)."""
from sizes import parse_size


class MyStr(str):
    pass


INPUTS = [
    # R5 existing
    "7", "0", "00", "007", "10KB", "2GB", "1MB", "", "KB", "-1", "1XB", "B",
    # R1 binary
    "1KiB", "1MiB", "1GiB", "3GiB", "1TiB", "1TB", "1KIB", "1kIb", "1K", "1k", "1Ki",
    # R2 case
    "10kb", "10Kb", "10kB", "1gib", "5b", "5B", "1mb", "1Mib",
    # R3 whitespace
    "10 KB", "10 kib", "1 B", "10  KB", "10\tKB", " 10KB", "10KB ", "10 ", " ",
    "10\n", "10KB\n", "\n10KB", "10 KB", "10 KB", "10　KB", "1 0KB",
    # R4 fractions
    "1.5KiB", "0.5KB", "1.3B", "0.1KiB", "1.5", "3.0", "0.5", "1.0B", "1.50KB",
    "0.0KB", "0.000KiB", "1.1KB", "4.35MB", "0.001KB", "0.0001KB", "0.0009765625KiB",
    "0.25 KiB", "1.123456789GB", "1.0000000001GiB", "2.5", ".5KB", "1.KB", "1.", ".",
    "1..5KB", "1.5.5KB", "1,5KB", "-1.5KB", "-0", "+1", "+1KB", "1e3", "1E3B", "1_000",
    "0x10", "inf", "nan", "1.5 KiB", "1.5  KiB",
    # Unicode digits / letters
    "١٠KB", "１０KB", "²KB", "١.٥KiB",
    "1KB", "1ＫB", "10İB",
    # large
    "99999999999999999999GiB", "123456789012345678901234567890",
    "1." + "0" * 60 + "1GiB",
]

for t in INPUTS:
    try:
        r = parse_size(t)
        out = "%s %r" % (type(r).__name__, r)
    except Exception as e:  # noqa: BLE001
        out = "EXC " + type(e).__name__
    print("%r -> %s" % (t, out))

for label, v in [("int", 10), ("float", 1.5), ("none", None), ("bytes", b"10KB"),
                 ("bytearray", bytearray(b"10")), ("list", ["10KB"]),
                 ("str-subclass", MyStr("10 KiB"))]:
    try:
        r = parse_size(v)
        out = "%s %r" % (type(r).__name__, r)
    except Exception as e:  # noqa: BLE001
        out = "EXC " + type(e).__name__
    print("<%s> -> %s" % (label, out))
