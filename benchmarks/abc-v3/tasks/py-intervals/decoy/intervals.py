def merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if s == e:
            continue
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            if s > e:
                raise ValueError("bad interval")
            out.append((s, e))
    return out


def subtract(a, b):
    out = []
    cuts = merge(b)
    for s, e in merge(a):
        for cs, ce in cuts:
            if cs <= s < ce:
                s = ce
            elif s < cs < e:
                out.append((s, cs))
                s = ce
        if s < e:
            out.append((s, e))
    return out


def total_length(intervals):
    return sum(e - s for s, e in merge(intervals))
