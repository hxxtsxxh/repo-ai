def _check(intervals):
    items = []
    for s, e in intervals:
        if s > e:
            raise ValueError("interval start is after end: %r" % ((s, e),))
        items.append((s, e))
    return items


def merge(intervals):
    out = []
    for s, e in sorted(i for i in _check(intervals) if i[0] < i[1]):
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def subtract(a, b):
    cuts = merge(b)
    out = []
    for s, e in merge(a):
        cur = s
        for cs, ce in cuts:
            if ce <= cur:
                continue
            if cs >= e:
                break
            if cs > cur:
                out.append((cur, cs))
            cur = max(cur, ce)
        if cur < e:
            out.append((cur, e))
    return merge(out)


def total_length(intervals):
    return sum(e - s for s, e in merge(intervals))
