import re
import time
from urllib.parse import quote

import aiohttp

from constants.base_url import INTERNETARCHIVE
from helper.author_utils import clean_archive_creators
from helper.session import get_connector

# Internet Archive - archive.org search (books, movies, audio, software...).
# Single advancedsearch request: title-only match (relevant results), size
# comes from fl[]=size so no per-item metadata round trips. Every item has
# a guaranteed _archive.torrent, so results always get a working .torrent
# button.

_AUDIOBOOK_RE = re.compile(r"\baudiobook\b|\baudio book\b|\blibrovox\b", re.I)

_MEDIATYPE_CATS = {
    "texts": "Books",
    "movies": "Movies",
    "audio": "Music",
    "etree": "Music",
    "software": "Apps",
    "image": "Other",
}


def _map_category(mediatype, title):
    if _AUDIOBOOK_RE.search(title or "") and mediatype in ("texts", "audio"):
        return "Audiobook"
    return _MEDIATYPE_CATS.get(mediatype, "Other")


class InternetArchive:
    _name = "Internet Archive"

    def __init__(self):
        self.BASE_URL = INTERNETARCHIVE
        self.LIMIT = None

    @staticmethod
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

    async def search(self, query, page, limit):
        start_time = time.time()
        per = limit or 15
        q = "title:({})".format(quote(query))
        url = self.BASE_URL + (
            "/advancedsearch.php?q={}&fl[]=identifier&fl[]=title"
            "&fl[]=mediatype&fl[]=date&fl[]=creator&fl[]=item_size"
            "&rows={}&page={}&output=json&sort[]=downloads+desc"
        ).format(quote(q), per, page)
        data = None
        for _attempt in range(2):
            try:
                async with aiohttp.ClientSession(
                    connector=get_connector(), connector_owner=False, trust_env=True
                ) as session:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=12)
                    ) as res:
                        if res.status != 200:
                            return None
                        data = await res.json(content_type=None)
                if data:
                    break
            except Exception:
                data = None
        if data is None:
            return None
        response = data.get("response") or {}
        docs = response.get("docs") or []
        total_found = int(response.get("numFound") or 0)
        results = []
        for d in docs:
            title = (d.get("title") or "").strip()
            identifier = d.get("identifier")
            if not title or len(title) < 5 or not identifier:
                continue
            if title.lower().startswith(("none", "unknown")):
                continue
            mediatype = d.get("mediatype") or ""
            obj = {
                "name": title,
                "url": self.BASE_URL + "/details/" + identifier,
                "torrent": self.BASE_URL + "/download/{}/{}_archive.torrent".format(
                    identifier, identifier
                ),
                "date": d.get("date"),
                "category": _map_category(mediatype, title),
            }
            size = d.get("item_size") or d.get("size")
            if size:
                obj["size_bytes"] = int(size)
                obj["size"] = self._format_size(size)
            authors = clean_archive_creators(d.get("creator"))
            if authors:
                obj["authors"] = authors
            results.append(obj)
        per = max(1, per)
        total_pages = max(1, -(-total_found // per)) if total_found else 1
        return {
            "data": results,
            "current_page": page,
            "total_pages": total_pages,
            "time": time.time() - start_time,
            "total": len(results),
        }

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
