def split_bill(total_cents, weights):
    if not weights or any(w < 0 for w in weights) or sum(weights) == 0 or total_cents < 0:
        raise ValueError("invalid split")
    total_weight = sum(weights)
    shares = [total_cents * w // total_weight for w in weights]
    shares[-1] += total_cents - sum(shares)
    return shares
