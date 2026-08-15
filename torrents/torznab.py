import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import aiohttp

from helper.session import get_connector

# Generic Torznab client - hooks up any Jackett / Prowlarr / Newznab
# compatible indexer without writing a scraper.
#
# Env config:
#   TORZNAB_URL        - base URL, e.g. http://127.0.0.1:9117 (Jackett)
#                        or http://127.0.0.1:9696 (Prowlarr)
#   TORZNAB_API_KEY    - indexer API key
#   TORZNAB_INDEXERS   - optional comma-separated indexer IDs (Prowlarr);
#                        empty = query the default/all configured indexers
#                        (Jackett ignores the indexers param entirely)

_TORZNAB_URL = (os.environ.get("TORZNAB_URL") or "").strip().rstrip("/")
_TORZNAB_API_KEY = (os.environ.get("TORZNAB_API_KEY") or "").strip()
_TORZNAB_INDEXERS = [
    i.strip()
    for i in (os.environ.get("TORZNAB_INDEXERS") or "").split(",")
    if i.strip()
]

_BTIH_HEX = re.compile(r"^[a-fA-F0-9]{40}$")
_BTIH_B32 = re.compile(r"^[A-Z2-7]{32}$")

# Standard Newznab/Torznab numeric categories -> t-api categories.
_CAT_RANGES = [
    ((3030, 3039), "Audiobook"),
    ((9000, 9039), "Books"),
    ((2000, 2999), "Movies"),
    ((5000, 5069), "TV"),
    ((5070, 5079), "Anime"),
    ((5080, 5089), "Documentaries"),
    ((3000, 3049), "Music"),
    ((4000, 4999), "Apps"),
    ((1000, 1999), "Games"),
    ((6000, 6999), "Games"),
    ((7000, 7999), "Games"),
    ((8000, 8999), "Other"),
]
_CAT_WORDS = [
    ("audiobook", "Audiobook"),
    ("book", "Books"),
    ("ebook", "Books"),
    ("movie", "Movies"),
    ("anime", "Anime"),
    ("documentary", "Documentaries"),
    ("tv", "TV"),
    ("music", "Music"),
    ("game", "Games"),
    ("software", "Apps"),
    ("app", "Apps"),
]


def _clean_hash(raw):
    if not raw:
        return None
    raw = str(raw).strip()
    if ":" in raw:
        raw = raw.rsplit(":", 1)[-1]
    raw = raw.upper().replace("-", "")
    if _BTIH_HEX.match(raw) or _BTIH_B32.match(raw):
        return raw
    return None


def _format_size(num):
    try:
        num = float(num)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if num < 1024 or unit == "TiB":
            return "{:.2f} {}".format(num, unit)
        num /= 1024
    return ""


def _map_category(text, attrs):
    tokens = [(w or "").lower() for w in (text or "").replace(",", " ").split()]
    codes = [int(w) for w in tokens if w.isdigit()]
    for key in ("category", "newznabcategory"):
        for v in attrs.get(key, []):
            try:
                codes.append(int(v))
            except (TypeError, ValueError):
                pass
    for word, cat in _CAT_WORDS:
        if any(word in w for w in tokens):
            return cat
    for code in codes:
        for (lo, hi), cat in _CAT_RANGES:
            if lo <= code <= hi:
                return cat
    return ""


def _attrs(children):
    """Map torznab:attr elements -> {name: [values]}."""
    out = {}
    for child in children:
        if child.tag.lower().endswith("attr"):
            name = child.get("name")
            value = child.get("value")
            if name and value is not None:
                out.setdefault(name.lower(), []).append(value)
    return out


def _parse(xml_text):
    root = ET.fromstring(xml_text)
    channel = root
    for child in root:
        if child.tag.lower().endswith("channel"):
            channel = child
            break
    rows = []
    for it in list(channel):
        if not it.tag.lower().endswith("item"):
            continue
        row = {"name": "", "size": "", "seeders": 0, "leechers": 0, "url": ""}
        enclosure = ""
        category_text = []
        attrs = _attrs(list(it))
        for child in it:
            tag = child.tag.lower()
            text = (child.text or "").strip()
            if tag.endswith("title"):
                row["name"] = text
            elif tag.endswith("size"):
                row["size_bytes"] = child.text
            elif tag.endswith("pubdate"):
                row["date"] = text
            elif tag.endswith("link"):
                if text and not row.get("url") and not text.startswith("magnet:"):
                    row["url"] = text
            elif tag.endswith("category"):
                if text:
                    category_text.append(text)
            elif tag.endswith("guid"):
                h = _clean_hash(text)
                if h:
                    row["hash"] = h
            elif tag.endswith("enclosure"):
                enclosure = child.get("url") or ""
        if not row["name"]:
            continue
        for key in ("infohash", "guid", "infoHash", "magnet"):
            for v in attrs.get(key, []):
                h = _clean_hash(v)
                if h:
                    row["hash"] = h
        for key, field in (
            ("seeders", "seeders"),
            ("seed", "seeders"),
            ("leechers", "leechers"),
            ("peers", "peers"),
        ):
            vals = attrs.get(key, [])
            if not vals:
                continue
            try:
                v = int(float(vals[0]))
            except (TypeError, ValueError):
                continue
            if field == "peers":
                if not row.get("seeders"):
                    row["seeders"] = v
                elif not row.get("leechers") and v >= row["seeders"]:
                    row["leechers"] = v - row["seeders"]
            else:
                row[field] = v
        link = row.get("url") or ""
        if enclosure.startswith("magnet:"):
            row["magnet"] = enclosure
        elif enclosure:
            row["torrent"] = enclosure
        elif link.startswith("magnet:"):
            row["magnet"] = link
        if row.get("size_bytes") is not None:
            row["size"] = _format_size(row["size_bytes"])
        cat = _map_category(" ".join(category_text), attrs)
        if cat:
            row["category"] = cat
        if not row.get("magnet") and row.get("hash"):
            row["magnet"] = "magnet:?xt=urn:btih:{}".format(row["hash"])
        if row.get("magnet") or row.get("torrent"):
            rows.append(row)
    return rows


class Torznab:
    _name = "Torznab"

    def __init__(self):
        self.BASE_URL = _TORZNAB_URL
        self.LIMIT = None

    async def _fetch(self, url):
        try:
            async with aiohttp.ClientSession(
                connector=get_connector(),
                connector_owner=False,
                trust_env=True,
            ) as session:
                async with session.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) t-api",
                        "X-Api-Key": _TORZNAB_API_KEY,
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as res:
                    if res.status != 200:
                        return None
                    return await res.text()
        except Exception:
            return None

    async def search(self, query, page, limit):
        start_time = time.time()
        if not self.BASE_URL or not _TORZNAB_API_KEY:
            return None
        per = limit or 50
        params = "t=search&q={}&limit={}&offset={}".format(
            quote(query), per, (page - 1) * per
        )
        if _TORZNAB_INDEXERS:
            params += "&indexers=" + ",".join(_TORZNAB_INDEXERS)
        url = "{}/api?apikey={}&{}".format(
            self.BASE_URL, _TORZNAB_API_KEY, params
        )
        xml_text = await self._fetch(url)
        if not xml_text:
            return None
        try:
            rows = _parse(xml_text)
        except Exception:
            return None
        total = len(rows)
        total_pages = 1
        if isinstance(xml_text, bytes):
            xml_text = xml_text.decode("utf-8", "ignore")
        m = re.search(r"<totalresults>\s*(\d+)", xml_text)
        if m:
            try:
                t = int(m.group(1))
                if t > total:
                    total = t
                    total_pages = max(1, -(-t // per))
            except ValueError:
                pass
        return {
            "data": rows[:per] if per else rows,
            "current_page": page,
            "total_pages": total_pages,
            "time": time.time() - start_time,
            "total": total,
        }

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
