import re
from datetime import datetime
from email.utils import parsedate_to_datetime

from helper.trackers import build_magnet, build_torrent_url
from helper.short_links import register, register_magnet


CATEGORY_ALIASES = {
    "course": ("course", "tutorial", "udemy", "training"),
    "book": ("book", "ebook", "audiobook", "novel", "pdf", "magazine"),
    "movie": ("movie", "film"),
    "tv": ("tv", "television"),
    "anime": ("anime",),
    "audiobook": ("audiobook", "audio book", "audio", "abook"),
    "music": ("music", "audio", "flac", "mp3"),
    "game": ("game",),
    "app": ("app", "software"),
}

# Categories where the result name is also checked (sites often don't set a
# category field, e.g. freecourseweb -> "The Complete Python Course 2024").
NAME_MATCH_CATEGORIES = {"course", "book", "music", "audiobook"}

# Name matching is looser than category matching for most filters, but for
# audiobooks the broad "audio" alias would pull movie rips ("DTS-HD 5.1
# Audio") when the site sets no category - keep the name check strict.
NAME_MATCH_STRICT = {
    "audiobook": ("audiobook", "audio book"),
}


_RES_RE = re.compile(r"(\d{3,4})p\b")

# A valid BitTorrent infohash is 40 hex chars (sha1) or 32 base32 chars.
# Other "hash"-looking values (e.g. libgen's 32-hex md5) cannot be turned
# into a working magnet/.torrent link, so don't fabricate one for them.
_BTIH_RE = re.compile(r"^[a-fA-F0-9]{40}$|^[A-Z2-7]{32}$")

# Language patterns are matched against name + category (+ any language
# field a scraper exposes). Short tokens (hin/tam/tel/... ) only match at a
# word start so release tags like "[Hin-Eng]", "HinDub", "[Tam+Tel]" work
# without false positives from substrings (e.g. "ben" inside "Unbent",
# "mar" inside "Driftmark"/"March", "tel" inside "Hotel").
_LANG_PATTERNS = {
    "hindi": re.compile(r"(?<![a-z0-9])(?:hindi|hin)", re.I),
    "english": re.compile(r"(?<![a-z0-9])(?:english|eng)", re.I),
    "tamil": re.compile(r"(?<![a-z0-9])(?:tamil|tam)", re.I),
    "telugu": re.compile(r"(?<![a-z0-9])(?:telugu|tel)", re.I),
    "malayalam": re.compile(r"(?<![a-z0-9])(?:malayalam|mal)", re.I),
    "kannada": re.compile(r"(?<![a-z0-9])(?:kannada|kan)", re.I),
    "bengali": re.compile(r"(?<![a-z0-9])bengali", re.I),
    "punjabi": re.compile(r"(?<![a-z0-9])punjabi", re.I),
    "marathi": re.compile(r"(?<![a-z0-9])marathi", re.I),
    "gujarati": re.compile(r"(?<![a-z0-9])gujarati", re.I),
    "dubbed": re.compile(r"(?<![a-z0-9])(?:dubbed|dub)", re.I),
    "dual": re.compile(r"(?<![a-z0-9])dual", re.I),
    "multi": re.compile(r"(?<![a-z0-9])multi", re.I),
}

# Order matters: longer/rarer extensions first so "azw3" wins over "azw"
# and "docx" over "doc".
_EBOOK_FORMATS = (
    "azw3", "djvu", "fb2", "epub", "mobi", "cbz", "cbr", "docx",
    "azw", "pdf", "txt", "doc", "lit", "rtf", "mp3", "m4b",
)


def _resolutions(name):
    """All resolutions present in a name (multi-quality releases like
    "720p 480p" report both, "4K/2160p/UHD" maps to 2160)."""
    res = set(int(m.group(1)) for m in _RES_RE.finditer(name or ""))
    if re.search(r"\b(4k|uhd|2160p)\b", name or "", re.I):
        res.add(2160)
    return res


def detect_quality(item):
    """Best resolution found in the result name, e.g. "1080p" / "4K"."""
    res = _resolutions(str(item.get("name") or ""))
    if not res:
        return None
    best = max(res)
    return "4K" if best >= 2160 else "{}p".format(best)


def detect_language(item):
    """Languages found in the result (name + category), e.g. "Hindi, English".

    Marker tokens (dubbed/dual/multi) are used for matching only, they are
    not reported as a language.
    """
    text = (
        str(item.get("name") or "") + " " + str(item.get("category") or "")
    ).lower()
    langs = []
    for label, pattern in _LANG_PATTERNS.items():
        if label in ("dubbed", "dual", "multi"):
            continue
        if pattern.search(text):
            langs.append(label.capitalize())
    return ", ".join(langs) if langs else None


def _ebook_format_in(text):
    """First ebook extension found in text, or None. Case-insensitive."""
    for f in _EBOOK_FORMATS:
        if re.search(r"(?<![a-z0-9])\.?" + re.escape(f) + r"(?![a-z0-9])", text):
            return f.upper()
    return None


def detect_format(item):
    """Book format found in name/category/extension/torrent url, e.g. "PDF"."""
    text = (
        str(item.get("name") or "") + " " + str(item.get("category") or "")
        + " " + str(item.get("extension") or "") + " "
        + str(item.get("torrent") or "") + " " + str(item.get("url") or "")
    ).lower()
    return _ebook_format_in(text)


def quality_matches(item, quality):
    """Match a movie result by resolution (480/720/1080/4k) using its name."""
    q = str(quality or "").lower().strip().replace("p", "")
    if not q:
        return True
    res = _resolutions(str(item.get("name") or ""))
    if not res:
        return False
    if q in ("4k", "2160"):
        return max(res) >= 2160
    try:
        return int(q) in res
    except ValueError:
        return False


def language_matches(item, language):
    """Match a result by language (hindi/english/tamil/dual/dubbed...).

    Also checks any language field a scraper exposes (libgen sets one), and
    "hindi" additionally covers Hindi dubbed releases.
    """
    lang = str(language or "").lower().strip()
    if not lang:
        return True
    text = (
        str(item.get("name") or "") + " " + str(item.get("category") or "")
        + " " + str(item.get("language") or "") + " "
        + str(item.get("languages") or "")
    ).lower()
    pattern = _LANG_PATTERNS.get(lang)
    if pattern is not None:
        return pattern.search(text) is not None
    return re.search(r"(?<![a-z0-9])" + re.escape(lang), text) is not None


def format_matches(item, fmt):
    """Match a book result by format (pdf/epub/mobi/azw3...) from its name,
    extension field or download/torrent URL."""
    f = str(fmt or "").lower().strip().lstrip(".")
    if not f:
        return True
    detected = detect_format(item)
    if detected and detected.lower() == f:
        return True
    text = (
        str(item.get("name") or "") + " " + str(item.get("category") or "")
        + " " + str(item.get("extension") or "")
    ).lower()
    return re.search(r"(?<![a-z0-9])\.?" + re.escape(f) + r"(?![a-z0-9])", text) is not None


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
        strict = NAME_MATCH_STRICT.get(category)
        if strict:
            return any(a in name for a in strict)
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


def parse_size(text):
    """Parse a size filter value into bytes.

    Accepts '500MB', '2GB', '1.5gb', '1024' (bare numbers are treated as
    MB) and raw byte counts (int). Returns None when unparseable.
    """
    if isinstance(text, (int, float)):
        return int(text)
    text = str(text or "").strip().lower()
    if not text:
        return None
    m = re.match(r"^([\d.]+)\s*([kmgt]?i?b)?$", text)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "mb").replace("ib", "b")
    mult = _SIZE_UNITS.get(unit)
    if not mult:
        return None
    return int(num * mult)


def _item_size_bytes(item):
    sb = item.get("size_bytes")
    if isinstance(sb, (int, float)):
        return int(sb)
    return size_to_bytes(item.get("size"))


def size_matches(item, min_size=None, max_size=None):
    """Match a result by size range (min_size/max_size accept '500MB', '2GB'
    or bare MB numbers). Items without a parseable size are excluded when a
    size filter is active."""
    low = parse_size(min_size)
    high = parse_size(max_size)
    if low is None and high is None:
        return True
    total = _item_size_bytes(item)
    if total is None:
        return False
    if low is not None and total < low:
        return False
    if high is not None and total > high:
        return False
    return True


def _seeders(item):
    seeds = _to_int(item.get("seeders"))
    return float(seeds) if isinstance(seeds, int) else -1


def clean_results(resp, sort=True, dedup=True):
    """Normalize, deduplicate and (optionally) sort results.

    Removes keys with None values (a None "torrent"/"magnet" would render a
    broken button in WZML-X). Deduplicates entries by hash (or normalized
    name/url when hash is missing) and sorts by seeders descending so the
    best releases come first. The "size" key is always kept (empty string
    when missing) so WZML-X never aborts rendering a result after its title
    line. dedup=False keeps every entry: multi-site endpoints (combo) do
    their own site-aware dedup and must not have whole sites silently
    dropped here when the same release appears on several sites.
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
            built_torrent = False
            if info_hash and _BTIH_RE.match(info_hash):
                if not item.get("torrent"):
                    item["torrent"] = build_torrent_url(
                        info_hash, item.get("name") or ""
                    )
                    built_torrent = True
                if not item.get("magnet"):
                    item["magnet"] = build_magnet(
                        info_hash, item.get("name") or ""
                    )
            if not (item.get("magnet") or item.get("torrent")):
                continue
            # Scrapers often leave the format unset; derive it from the
            # download link (oceanofpdf ...pdf, hindiaudio ...mp3) or mark
            # hash-built .torrent links so bot filenames get a real
            # extension instead of the .dl fallback.
            if item.get("extension") is None:
                _link_text = (
                    str(item.get("torrent") or "") + " "
                    + str(item.get("download") or "")
                )
                _fm = re.search(
                    r"\.(azw3|djvu|fb2|epub|mobi|cbz|cbr|docx|azw|pdf|txt|doc|lit|rtf|mp3|m4b|torrent)(?:[?#]|$)",
                    _link_text, re.I,
                )
                if _fm:
                    item["extension"] = _fm.group(1).lower()
                elif built_torrent:
                    item["extension"] = "torrent"
            # Enrich with detected metadata so WZML and API clients can show
            # quality/language (movies) and format (books) without parsing names.
            for _key, _detect in (
                ("quality", detect_quality),
                ("language", detect_language),
                ("format", detect_format),
            ):
                if item.get(_key) is None:
                    _val = _detect(item)
                    if _val:
                        item[_key] = _val
            for key in ("seeders", "leechers", "downloads"):
                if item.get(key) is not None:
                    item[key] = _to_int(item[key])
            if item.get("size") is not None and "size_bytes" not in item:
                size_bytes = size_to_bytes(item.get("size"))
                if size_bytes:
                    item["size_bytes"] = size_bytes
            if "size" not in item:
                item["size"] = ""
            if item.get("torrent") and not item.get("short"):
                item["short"] = register(
                    item["torrent"], item.get("name") or "", item.get("extension") or ""
                )
            if item.get("magnet") and not item.get("magnet_short"):
                item["magnet_short"] = register_magnet(item["magnet"])
        cleaned.append(item)

    if dedup:
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
    else:
        deduped = cleaned

    if sort:
        deduped.sort(key=_seeders, reverse=True)
    resp["data"] = deduped
    if "total" in resp:
        resp["total"] = len(deduped)
    return resp


def size_to_bytes(text):
    """Public wrapper around the size parser (used for size sorting).

    Accepts the same formats as parse_size: '500MB', '2GB', '1.5gb' and
    bare numbers (treated as MB)."""
    return _size_to_bytes(text) or parse_size(text)


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
    elif sort == "quality":
        data.sort(
            key=lambda i: max(_resolutions(str(i.get("name") or "")) or [0]),
            reverse=reverse,
        )
    else:
        data.sort(key=_seeders, reverse=reverse)
    return data
