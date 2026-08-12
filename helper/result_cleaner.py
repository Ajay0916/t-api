import re
from datetime import datetime
from email.utils import parsedate_to_datetime

from helper.trackers import build_magnet, build_torrent_url


CATEGORY_ALIASES = {
    "course": ("course", "tutorial", "udemy", "training"),
    "book": ("book", "ebook", "audiobook", "novel", "pdf", "magazine"),
    "movie": ("movie", "film"),
    "tv": ("tv", "television"),
    "anime": ("anime",),
    "music": ("music", "audio", "flac", "mp3"),
    "game": ("game",),
    "app": ("app", "software"),
}

# Categories where the result name is also checked (sites often don't set a
# category field, e.g. freecourseweb -> "The Complete Python Course 2024").
NAME_MATCH_CATEGORIES = {"course", "book", "music"}


def category_matches(item, category):
    """Match a category keyword against a result's category or name.

    Accepts plural keywords too (courses/books/movies/apps/games) so WZML's
    category buttons work even when sites label things differently."""
    cat = str(item.get("category") or "").lower()
    aliases = CATEGORY_ALIASES.get(category)
    if aliases is None and category.endswith("s") and len(category) > 3:
        aliases = CATEGORY_ALIASES.get(category[:-1])
    if aliases is None:
        aliases = (category,)
    if any(a in cat for a in aliases):
        return True
    if category in NAME_MATCH_CATEGORIES or (
        category.endswith("s") and category[:-1] in NAME_MATCH_CATEGORIES
    ):
        name = str(item.get("name") or "").lower()
        return any(a in name for a in aliases)
    return False


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
            # WZML-X renders a button from magnet/torrent; results with
            # neither are useless, so drop them. Before dropping, build any
            # missing link from the infohash so hash-bearing results always
            # give WZML a Direct Link (.torrent) AND a magnet.
            info_hash = str(item.get("hash") or "").strip()
            if info_hash:
                if not item.get("torrent"):
                    item["torrent"] = build_torrent_url(
                        info_hash, item.get("name") or ""
                    )
                if not item.get("magnet"):
                    item["magnet"] = build_magnet(
                        info_hash, item.get("name") or ""
                    )
            if not (item.get("magnet") or item.get("torrent")):
                continue
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


def size_to_bytes(text):
    """Public wrapper around the size parser (used for size sorting)."""
    return _size_to_bytes(text)


def parse_date(text):
    """Best-effort date parser -> unix timestamp, or None if unparseable.

    Handles ISO, RFC-2822, and common torrent-site formats. Relative dates
    ("Today", "1 year ago") return None so they sort to the end.
    """
    if not text:
        return None
    text = str(text).strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError, OverflowError):
        pass
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%d %b %y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            pass
    m = re.search(r"([A-Za-z]{3,9})[.\s]*(\d{1,2})[a-z]{0,2}[,\s]+'?(\d{2,4})", text)
    if m:
        try:
            return datetime.strptime(
                "{} {} {}".format(m.group(1)[:3].capitalize(), m.group(2), m.group(3)),
                "%b %d %y",
            ).timestamp()
        except ValueError:
            pass
    return None


def sort_results(data, sort="seeders", order="desc"):
    """Sort result rows in place by seeders/size/date (default seeders desc)."""
    reverse = str(order).lower() != "asc"
    if sort == "size":
        data.sort(
            key=lambda i: (i.get("size_bytes") or size_to_bytes(i.get("size")) or 0),
            reverse=reverse,
        )
    elif sort == "date":
        data.sort(
            key=lambda i: parse_date(i.get("date")) or 0, reverse=reverse
        )
    else:
        data.sort(key=_seeders, reverse=reverse)
    return data
