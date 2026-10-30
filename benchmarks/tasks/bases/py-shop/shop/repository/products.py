from shop.repository.memory import InMemoryRepository


class ProductRepository(InMemoryRepository):
    entity = "product"
    key_attr = "sku"

    def by_slug(self, slug: str):
        for product in self._items.values():
            if product.slug == slug:
                return product
        return None

    def slugs(self) -> set:
        return {p.slug for p in self._items.values()}

    def active(self, tag=None) -> list:
        def keep(p):
            return p.active and (tag is None or tag in p.tags)

        return self.list(keep)
