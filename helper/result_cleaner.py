import re


def _norm(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


_SIZE_RE = re.compile(r"([\d.,]+\s?)([kmgt]?i?b)\b", re.I)
_SIZE_UNITS = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}


def _size_to_bytes(text):
    try:
        m = _SIZE_RE.search(str(text or ""))
        if not m:
            return None
        num = float(m.group(1).replace(",", ""))
        unit = m.group(2).lower().replace("ib", "b")
        multiplier = _SIZE_UNITS.get(unit)
        if not multiplier:
            return None
        return int(num * multiplier)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return value


def _seeders(item):
    seeds = _to_int(item.get("seeders"))
    return float(seeds) if isinstance(seeds, int) else -1


def clean_results(resp, sort=True):
    """Normalize, deduplicate and (optionally) sort results.

    Removes keys with None values (a None "torrent"/"magnet" would render a
    broken button in WZML-X). Deduplicates entries by hash (or normalized
    name/url when hash is missing) and sorts by seeders descending so the
    best releases come first. The "size" key is always kept (empty string
    when missing) so WZML-X never aborts rendering a result after its title
    line.
    """
    if not isinstance(resp, dict):
        return resp
    data = resp.get("data")
    if not isinstance(data, list):
        return resp
    cleaned = []
    for item in data:
        if isinstance(item, dict):
            item = {k: v for k, v in item.items() if v is not None}
            for key in ("seeders", "leechers", "downloads"):
                if item.get(key) is not None:
                    item[key] = _to_int(item[key])
            if item.get("size") is not None and "size_bytes" not in item:
                size_bytes = _size_to_bytes(item.get("size"))
                if size_bytes:
                    item["size_bytes"] = size_bytes
            if "size" not in item:
                item["size"] = ""
        cleaned.append(item)

    seen = set()
    deduped = []
    for item in cleaned:
        if not isinstance(item, dict):
            deduped.append(item)
            continue
        key = None
        if item.get("hash"):
            key = ("h", str(item["hash"]).lower())
        elif item.get("name"):
            key = ("n", _norm(item["name"]))
        elif item.get("url"):
            key = ("u", _norm(item["url"]))
        if key:
            if key in seen:
                continue
            seen.add(key)
        deduped.append(item)

    if sort:
        deduped.sort(key=_seeders, reverse=True)
    resp["data"] = deduped
    if "total" in resp:
        resp["total"] = len(deduped)
    return resp
