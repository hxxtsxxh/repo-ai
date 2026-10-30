import re

_ID = r"[0-9A-Za-z-]+"
_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(" + _ID + r"(?:\." + _ID + r")*))?(?:\+(" + _ID + r"(?:\." + _ID + r")*))?\Z")


def _parse(v):
    if not isinstance(v, str):
        raise ValueError("not a string")
    m = _RE.match(v)
    if not m:
        raise ValueError("invalid version")
    pre = m[4].split(".") if m[4] is not None else None
    if pre is not None:
        for ident in pre:
            if ident.isdigit() and len(ident) > 1 and ident[0] == "0":
                raise ValueError("leading zero in numeric identifier")
    return (int(m[1]), int(m[2]), int(m[3])), pre


def _cmp(x, y):
    return (x > y) - (x < y)


def compare_versions(a, b):
    (na, pa), (nb, pb) = _parse(a), _parse(b)
    if na != nb:
        return _cmp(na, nb)
    if pa is None and pb is None:
        return 0
    if pa is None:
        return 1
    if pb is None:
        return -1
    for x, y in zip(pa, pb, strict=False):
        xd, yd = x.isdigit(), y.isdigit()
        if xd and yd:
            r = _cmp(int(x), int(y))
        elif xd != yd:
            r = -1 if xd else 1
        else:
            r = _cmp(x, y)
        if r:
            return r
    return _cmp(len(pa), len(pb))
