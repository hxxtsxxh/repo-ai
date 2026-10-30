"""Runtime configuration for the shop service.

Values are plain module-level constants so tests can override them with
``unittest.mock.patch.object(config, "NAME", value)``.
"""

import os

APP_NAME = "py-shop"
DEFAULT_CURRENCY = "USD"
SUPPORTED_CURRENCIES = ("USD", "EUR", "GBP")

# --- Authentication -------------------------------------------------------
TOKEN_SECRET = os.environ.get("SHOP_TOKEN_SECRET", "dev-only-not-a-secret")
TOKEN_TTL_MINUTES = 60
PASSWORD_HASH_ITERATIONS = 20_000

# --- Pagination -----------------------------------------------------------
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# --- Tax ------------------------------------------------------------------
# Rates in basis points (1 bp = 0.01 %), keyed by two-letter region code.
TAX_RATES_BP = {
    "CA": 725,
    "NY": 400,
    "TX": 625,
    "WA": 650,
    "OR": 0,
}

# --- Shipping -------------------------------------------------------------
SHIPPING_RATES_CENTS = {"standard": 599, "express": 1499}
FREE_SHIPPING_THRESHOLD_CENTS = 5000

# --- Inventory ------------------------------------------------------------
LOW_STOCK_THRESHOLD = 5

# --- Notifications --------------------------------------------------------
NOTIFY_FROM_ADDRESS = "orders@shop.invalid"
