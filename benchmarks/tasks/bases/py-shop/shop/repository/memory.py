"""Generic dict-backed repository with insertion-ordered listing."""

from shop.errors import Conflict, NotFound


class InMemoryRepository:
    entity = "item"
    key_attr = "id"
    id_prefix = "itm"

    def __init__(self):
        self._items = {}
        self._counter = 0

    def next_id(self) -> str:
        self._counter += 1
        return f"{self.id_prefix}_{self._counter:04d}"

    def _key(self, item):
        return getattr(item, self.key_attr)

    def add(self, item):
        key = self._key(item)
        if key in self._items:
            raise Conflict(f"{self.entity} {key} already exists")
        self._items[key] = item
        return item

    def get(self, key):
        return self._items.get(key)

    def require(self, key):
        item = self._items.get(key)
        if item is None:
            raise NotFound(f"{self.entity} {key} not found")
        return item

    def update(self, item):
        key = self._key(item)
        if key not in self._items:
            raise NotFound(f"{self.entity} {key} not found")
        self._items[key] = item
        return item

    def delete(self, key) -> None:
        self._items.pop(key, None)

    def list(self, predicate=None) -> list:
        values = list(self._items.values())
        if predicate is None:
            return values
        return [v for v in values if predicate(v)]

    def __len__(self) -> int:
        return len(self._items)
