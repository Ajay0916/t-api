import re


def _norm(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


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
