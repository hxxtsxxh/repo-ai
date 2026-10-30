class TTLCache:
    """Small time-to-live cache. Time is passed in explicitly so behavior is deterministic."""

    def __init__(self, ttl):
        self.ttl = ttl
        self._data = {}

    def set(self, key, value, now):
        self._data.setdefault(key, (value, now))

    def get(self, key, now, default=None):
        item = self._data.get(key)
        if item is None:
            return default
        value, stored = item
        if now - stored > self.ttl:
            return default
        return value

    def __len__(self):
        return len(self._data)
