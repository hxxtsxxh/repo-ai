import re

_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")


def _parse(v):
    if not isinstance(v, str):
        raise ValueError("not a string")
    m = _RE.match(v)
    if not m:
        raise ValueError("invalid version")
    return (int(m[1]), int(m[2]), int(m[3])), m[4]


def compare_versions(a, b):
    (na, pa), (nb, pb) = _parse(a), _parse(b)
    if na != nb:
        return -1 if na < nb else 1
    if pa == pb:
        return 0
    if pa is None:
        return 1
    if pb is None:
        return -1
    return -1 if pa < pb else 1
