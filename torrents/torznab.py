import asyncio
import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote, unquote, urlparse

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
#                        empty = auto-discover all enabled Prowlarr indexers
#                        (Jackett ignores the indexers param entirely)
#
# Prowlarr exposes each indexer at /{id}/api (id=0 is only a test stub), so
# one query per indexer is fired concurrently and merged. Prowlarr rewrites
# download/magnet links to its own /{id}/download?link=... proxy - those are
# decoded back to the real URL, and the torznab "infohash" attr is used to
# build working magnet + .torrent links.

_TORZNAB_URL = (os.environ.get("TORZNAB_URL") or "").strip().rstrip("/")
_TORZNAB_API_KEY = (os.environ.get("TORZNAB_API_KEY") or "").strip()
_TORZNAB_INDEXERS = [
    i.strip()
    for i in (os.environ.get("TORZNAB_INDEXERS") or "").split(",")
    if i.strip()
]

_BTIH_HEX = re.compile(r"^[a-fA-F0-9]{40}$")
_BTIH_B32 = re.compile(r"^[A-Z2-7]{32}$")
_DL_PROXY_RE = re.compile(r"/\d+/download\b")

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


def _magnet_hash(raw):
    if not raw or not raw.lower().startswith("magnet:"):
        return None
    m = re.search(r"xt=urn:btih:([a-fA-F0-9]{40}|[A-Z2-7]{32})", raw)
    if not m:
        return None
    return m.group(1).upper()


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


def _unproxy(url):
    """Decode a Prowlarr /{id}/download?link=... proxy URL back to the real
    magnet or download URL. Plain magnet:/http(s) URLs pass through."""
    if not url:
        return None, None
    u = urlparse(url)
    if u.scheme == "magnet":
        return "magnet", url
    if _DL_PROXY_RE.search(u.path) and u.query:
        q = parse_qs(u.query)
        target = q.get("link", [None])[0]
        if target:
            target = unquote(target)
            if target.lower().startswith("magnet:"):
                return "magnet", target
            if target.lower().startswith(("http://", "https://")):
                return "torrent", target
    if u.scheme in ("http", "https"):
        return "torrent", url
    return None, None


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
        link = ""
        comments = ""
        guid = ""
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
            elif tag.endswith("comments"):
                comments = text
            elif tag.endswith("link"):
                link = text
            elif tag.endswith("category"):
                if text:
                    category_text.append(text)
            elif tag.endswith("guid"):
                guid = text
            elif tag.endswith("enclosure"):
                enclosure = child.get("url") or ""
        if not row["name"]:
            continue
        for key in ("infohash", "guid", "infoHash"):
            for v in attrs.get(key, []):
                h = _clean_hash(v)
                if h:
                    row["hash"] = h
                    break
            if row.get("hash"):
                break
        if not row.get("hash"):
            h = _clean_hash(guid) or _magnet_hash(guid)
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
        download = enclosure or link
        kind, real = _unproxy(download)
        if kind == "magnet":
            row["magnet"] = real
            if not row.get("hash"):
                h = _magnet_hash(real)
                if h:
                    row["hash"] = h
        elif kind == "torrent":
            row["torrent"] = real
        if comments and comments.startswith("http"):
            row["url"] = comments
        elif link.startswith("http") and link != real:
            row["url"] = link
        if row.get("size_bytes") is not None:
            row["size"] = _format_size(row["size_bytes"])
        cat = _map_category(" ".join(category_text), attrs)
        if cat:
            row["category"] = cat
        langs = attrs.get("language")
        if langs:
            row["languages"] = [l for l in langs if l]
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

    def _headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) t-api",
            "X-Api-Key": _TORZNAB_API_KEY,
        }

    async def _fetch(self, url, timeout=30):
        try:
            async with aiohttp.ClientSession(
                connector=get_connector(),
                connector_owner=False,
                trust_env=True,
            ) as session:
                async with session.get(
                    url,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as res:
                    if res.status != 200:
                        return None
                    return await res.text()
        except Exception:
            return None

    async def _discover_ids(self):
        """List of enabled Prowlarr indexer IDs, or None on request failure."""
        data = await self._fetch(
            "{}/api/v1/indexer".format(self.BASE_URL), timeout=10
        )
        if not data:
            return None
        try:
            import json
            indexers = json.loads(data)
        except Exception:
            return None
        return [
            int(i["id"])
            for i in indexers
            if i.get("enable", True) and not i.get("isReadOnly")
        ]

    async def _search_indexer(self, indexer_id, query, per, page, sem):
        async with sem:
            params = "t=search&q={}&limit={}&offset={}".format(
                quote(query), per, (page - 1) * per
            )
            url = "{}/{}/api?apikey={}&{}".format(
                self.BASE_URL, indexer_id, _TORZNAB_API_KEY, params
            )
            xml_text = await self._fetch(url, timeout=25)
            if not xml_text:
                return []
            try:
                return _parse(xml_text)
            except Exception:
                return []

    async def search(self, query, page, limit):
        start_time = time.time()
        if not self.BASE_URL or not _TORZNAB_API_KEY:
            return None
        per = limit or 50
        if _TORZNAB_INDEXERS:
            ids = [int(i) for i in _TORZNAB_INDEXERS if i.isdigit()]
        else:
            ids = await self._discover_ids()
        if ids is None:
            return None
        if not ids:
            return {
                "data": [],
                "current_page": page,
                "total_pages": 1,
                "time": time.time() - start_time,
                "total": 0,
            }
        sem = asyncio.Semaphore(4)
        tasks = [
            asyncio.create_task(self._search_indexer(i, query, per, page, sem))
            for i in ids
        ]
        done, pending = await asyncio.wait(tasks, timeout=22)
        for t in pending:
            t.cancel()
        chunks = []
        for t in done:
            try:
                res = t.result()
            except Exception:
                continue
            if res:
                chunks.append(res)
        rows = []
        seen = set()
        for chunk in chunks:
            for r in chunk:
                key = r.get("hash") or "{}|{}".format(
                    r.get("name", "").lower(), r.get("torrent") or r.get("url")
                )
                if key in seen:
                    continue
                seen.add(key)
                rows.append(r)
        rows.sort(key=lambda r: r.get("seeders") or 0, reverse=True)
        rows = rows[:per]
        return {
            "data": rows,
            "current_page": page,
            "total_pages": 1,
            "time": time.time() - start_time,
            "total": len(rows),
        }

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
