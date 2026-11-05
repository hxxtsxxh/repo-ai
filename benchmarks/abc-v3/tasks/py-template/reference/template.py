import re

_NAME = re.compile(r"^\w+(\.\w+)*$", re.ASCII)
_ESC = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"), ("'", "&#x27;"))


def _lookup(path, context):
    cur = context
    for seg in path.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        elif isinstance(cur, list) and seg.isascii() and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            raise KeyError(path)
    return cur


def _text(value):
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _placeholder(body, context):
    path, sep, flt = body.partition("|")
    path = path.strip()
    if not _NAME.match(path):
        raise ValueError("malformed path: %r" % path)
    raw = False
    if sep:
        if flt.strip() != "raw":
            raise ValueError("unknown filter: %r" % flt.strip())
        raw = True
    text = _text(_lookup(path, context))
    if not raw:
        for a, b in _ESC:
            text = text.replace(a, b)
    return text


def render(template, context):
    out, i, n = [], 0, len(template)
    while i < n:
        if template.startswith("\\{{", i):
            out.append("{{")
            i += 3
        elif template.startswith("{{", i):
            j = template.find("}}", i + 2)
            if j < 0:
                raise ValueError("unclosed placeholder")
            out.append(_placeholder(template[i + 2:j], context))
            i = j + 2
        else:
            out.append(template[i])
            i += 1
    return "".join(out)
