import hashlib
import json
import os
import threading
import time

# Tiny persistent store mapping a short token -> the real proxy URL + name.
# Lets the bot hand out /api/v1/torrent_file/<token> links instead of
# carrying the full url=...&name=... query (rutracker/libgen titles make
# those links 1KB+). Entries expire after the TTL and are pruned on write.
_TTL = 14 * 24 * 3600
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache_data")
_FILE = os.path.join(_DIR, "shortlinks.json")
_lock = threading.Lock()
_links = None


def _load():
    global _links
    if _links is None:
        try:
            with open(_FILE, encoding="utf-8") as fh:
                _links = json.load(fh)
        except Exception:
            _links = {}
    return _links


def _save():
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_FILE, "w", encoding="utf-8") as fh:
            json.dump(_links, fh)
    except Exception:
        pass


def _token(url, name, ext):
    return hashlib.md5(
        "{}|{}|{}".format(url, name, ext or "").encode("utf-8")
    ).hexdigest()[:12]


def register(url, name="", ext=""):
    """Store url/name/ext and return a short token for it ("" if no url)."""
    if not url:
        return ""
    with _lock:
        _load()
        now = time.time()
        for key in [k for k, v in _links.items() if now - v.get("t", 0) > _TTL]:
            _links.pop(key, None)
        token = _token(url, name, ext)
        existing = _links.get(token)
        if existing and existing.get("url") == url:
            existing["t"] = now
            existing["name"] = name
            existing["ext"] = ext or ""
        else:
            if existing:
                token += hashlib.md5(str(now).encode()).hexdigest()[:4]
            _links[token] = {
                "url": url,
                "name": name,
                "ext": ext or "",
                "t": now,
            }
        _save()
        return token


def lookup(token):
    """Return {"url","name","ext"} for a token, or None if unknown/expired."""
    if not token:
        return None
    with _lock:
        _load()
        info = _links.get(token)
        if not info:
            return None
        if time.time() - info.get("t", 0) > _TTL:
            _links.pop(token, None)
            _save()
            return None
        return info


def register_magnet(magnet):
    """Store a magnet and return a short token for it ("" if none)."""
    return register(magnet)
