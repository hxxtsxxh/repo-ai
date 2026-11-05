# py-shop

A small, dependency-free order management service used for experiments.
Everything runs on the Python 3.10+ standard library: there is no web
framework, no database and no third-party package.

## Layout

| Path | What lives there |
| --- | --- |
| `shop/config.py` | Module-level settings (tax table, shipping rates, page sizes, token lifetime) |
| `shop/models/` | Dataclasses for products, orders, users and payments |
| `shop/repository/` | In-memory repositories keyed by id |
| `shop/services/` | Business logic: orders, payments, inventory, pricing, discounts, shipping, notifications, auth, users |
| `shop/utils/` | Money helpers (integer cents), dates, validation, slugs, pagination |
| `shop/api/` | Request handlers, the route table and the tiny router |
| `shop/app.py` | Wires everything together; `create_app()` returns an `App` with demo data |

Requests are plain dicts (`method`, `path`, `headers`, `query`, `body`) and
responses are dicts with `status`, `headers` and `body`.

```python
from shop.app import create_app

app = create_app()
resp = app.request("POST", "/auth/login", body={"email": "admin@shop.invalid", "password": "admin-pass-123"})
token = resp["body"]["token"]
app.request("GET", "/products", headers={"Authorization": f"Bearer {token}"})
```

## Conventions

* Money is always integer cents. Convert user input with
  `shop.utils.money.to_cents` and display it with `format_money`.
  Rounding is half-up to the nearest cent everywhere.
* Tax rates are stored in basis points per two-letter region code.
* Standard shipping is free once the discounted subtotal reaches
  `FREE_SHIPPING_THRESHOLD_CENTS`; express shipping is never free.
* Delivery estimates count business days only (Monday to Friday).
* Access tokens are HMAC-signed and valid for `TOKEN_TTL_MINUTES`
  (one hour by default).
* List endpoints accept `page` and `per_page`; `per_page` is capped at
  `MAX_PAGE_SIZE` (100).

## Running the tests

```
make test
```

or directly:

```
python3 -m unittest discover -s tests -t .
```
