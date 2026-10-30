import re


def _lookup(path, context):
    cur = context
    for seg in path.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        elif isinstance(cur, list) and seg.isdigit() and int(seg) < len(cur):
            cur = cur[int(seg)]
        else:
            raise KeyError(path)
    return cur


def render(template, context):
    def sub(m):
        body = m.group(1)
        path, sep, flt = body.partition("|")
        if sep and flt.strip() != "raw":
            raise ValueError("filter")
        text = str(_lookup(path.strip(), context))
        if not sep:
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return text
    return re.sub(r"\{\{(.*?)\}\}", sub, template)
