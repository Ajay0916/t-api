import copy
import json
import os
import time
from collections import OrderedDict

CACHE_DIR = os.environ.get("TORRENTS_CACHE_DIR", "cache_data")
CACHE_WRITE_INTERVAL = 60.0


class TTLCache:
    """TTL cache with simple FIFO eviction and optional disk persistence.

    A snapshot of the cache is written to ``cache_data/{name}.json`` when the
    process is restarted frequently (VPS deploys), so popular queries survive
    restarts. Writes are throttled to once per ``CACHE_WRITE_INTERVAL``.
    """

    def __init__(self, max_size=256, ttl=300, name=""):
        self.max_size = max_size
        self.ttl = ttl
        self.name = name
        self._data = OrderedDict()
        self._last_write = 0.0

    def get(self, key):
        item = self._data.get(key)
        if item is None:
            return None
        expiry, value = item
        if time.time() > expiry:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return copy.deepcopy(value)

    def set(self, key, value, ttl=None):
        expiry = time.time() + (ttl or self.ttl)
        self._data[key] = (expiry, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)
        self._maybe_persist()

    def clear(self):
        self._data.clear()
        self._maybe_persist(force=True)

    def persist(self, force=False):
        if not self.name:
            return
        try:
            payload = [
                (key, expiry, value)
                for key, (expiry, value) in self._data.items()
                if expiry > time.time()
            ]
            os.makedirs(CACHE_DIR, exist_ok=True)
            path = os.path.join(CACHE_DIR, self.name + ".json")
            with open(path, "w") as f:
                json.dump(payload, f, default=str)
        except Exception:
            pass

    def _maybe_persist(self, force=False):
        now = time.time()
        if force or now - self._last_write >= CACHE_WRITE_INTERVAL:
            self._last_write = now
            self.persist()

    def load(self):
        if not self.name:
            return
        try:
            path = os.path.join(CACHE_DIR, self.name + ".json")
            with open(path) as f:
                payload = json.load(f)
            now = time.time()
            for entry in payload:
                try:
                    key, expiry, value = entry
                except (TypeError, ValueError):
                    continue
                if expiry > now and len(self._data) < self.max_size:
                    self._data[key] = (expiry, value)
        except Exception:
            pass


search_cache = TTLCache(max_size=256, ttl=300, name="search")
combo_cache = TTLCache(max_size=128, ttl=300, name="combo")
rss_cache = TTLCache(max_size=64, ttl=300, name="rss")

search_cache.load()
combo_cache.load()
rss_cache.load()
