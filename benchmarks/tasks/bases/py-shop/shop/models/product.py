from dataclasses import dataclass, field


@dataclass
class Product:
    sku: str
    name: str
    price_cents: int
    currency: str = "USD"
    slug: str = ""
    active: bool = True
    tags: list = field(default_factory=list)
