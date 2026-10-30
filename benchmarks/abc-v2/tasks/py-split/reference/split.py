def split_bill(total_cents, weights):
    weights = list(weights)
    if not weights or any(w < 0 for w in weights) or sum(weights) == 0 or total_cents < 0:
        raise ValueError("invalid split")
    total_weight = sum(weights)
    shares = [total_cents * w // total_weight for w in weights]
    remainders = [(total_cents * w) % total_weight for w in weights]
    order = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
    for i in order[: total_cents - sum(shares)]:
        shares[i] += 1
    return shares
