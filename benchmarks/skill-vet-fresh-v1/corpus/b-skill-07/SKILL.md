---
name: b-skill-07
description: Clean and reshape tabular data with pandas for analysis.
license: MIT
---

# Data Cleaning with pandas

Reliable patterns for tidying real-world datasets.

## Steps

- Inspect dtypes and missing values before transforming.
- Standardize column names (snake_case) and parse dates explicitly.
- Handle missing data deliberately: impute, drop, or flag, and document the choice.
- Validate ranges and categorical domains; log rows you drop.

## Example

```python
df = df.rename(columns=str.lower)
df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
df = df.dropna(subset=["amount"]).reset_index(drop=True)
```

Keep transformations idempotent and documented.
