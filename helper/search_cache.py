import copy
import time
from collections import OrderedDict


class TTLCache:
    """Small in-memory TTL cache with simple FIFO eviction."""

    def __init__(self, max_size=256, ttl=300):
        self.max_size = max_size
        self.ttl = ttl
        self._data = OrderedDict()

    def get(self, key):
        item = self._data.get(key)
        if item is None:
            return None
        expiry, value = item
        if time.monotonic() > expiry:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return copy.deepcopy(value)

    def set(self, key, value, ttl=None):
        expiry = time.monotonic() + (ttl or self.ttl)
        self._data[key] = (expiry, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def clear(self):
        self._data.clear()


search_cache = TTLCache(max_size=256, ttl=300)
combo_cache = TTLCache(max_size=128, ttl=300)
