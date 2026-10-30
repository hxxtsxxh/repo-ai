def split_bill(total_cents, weights):
    total_weight = sum(weights)
    return [round(total_cents * w / total_weight) for w in weights]
