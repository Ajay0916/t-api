import json
import re
import time
from urllib.parse import quote

import aiohttp
from constants.base_url import PIRATEBAY
from constants.headers import HEADER_AIO, AIO_TIMEOUT
from helper.trackers import build_magnet
from helper.session import get_connector
from torrents.torrent_galaxy import format_date, format_size

TORRENT_CDN = "https://itorrents.org/torrent/{}.torrent"


def _category(cat):
    try:
        cat = int(cat)
    except (TypeError, ValueError):
        return None
    if 100 <= cat < 200:
        return "Audio"
    if 200 <= cat < 300:
        return "TV" if cat in (205, 208) else "Movies"
    if 300 <= cat < 400:
        return "Apps"
    if 400 <= cat < 500:
        return "Games"
    if 500 <= cat < 600:
        return "Porn"
    if 600 <= cat < 700:
        return "Books" if cat == 604 else "Other"
    return None


class PirateBay:
    _name = "Pirate Bay"

    def __init__(self):
        self.BASE_URL = PIRATEBAY
        self.LIMIT = None

    @staticmethod
    def _build_item(item):
        name = item.get("name")
        if not name or str(item.get("id")) == "0":
            return None
        if str(name).strip().lower().startswith("no results"):
            return None
        info_hash = (item.get("info_hash") or "").strip()
        if not re.fullmatch(r"[a-f0-9]{40}", info_hash.lower()):
            return None
        return {
            "name": name,
            "size": format_size(item.get("size")),
            "date": format_date(item.get("added")),
            "seeders": item.get("seeders"),
            "leechers": item.get("leechers"),
            "category": _category(item.get("category")),
            "uploader": item.get("username") or "",
            "url": "{}/t.php?id={}".format(PIRATEBAY, item.get("id")),
            "hash": info_hash,
            "magnet": build_magnet(info_hash, name) if info_hash else None,
            "torrent": TORRENT_CDN.format(info_hash) if info_hash else None,
            "imdb_id": item.get("imdb") or None,
        }

    async def _fetch(self, url):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            async with session.get(url, headers=HEADER_AIO, timeout=AIO_TIMEOUT) as res:
                return json.loads(await res.text())

    async def _results(self, url, start_time):
        try:
            data = await self._fetch(url)
        except Exception:
            return None
        if not isinstance(data, list):
            return None
        results = []
        for item in data:
            parsed = self._build_item(item)
            if parsed is None:
                continue
            results.append(parsed)
            if self.LIMIT and len(results) >= self.LIMIT:
                break
        return {
            "data": results,
            "current_page": 1,
            "total_pages": 1,
            "time": time.time() - start_time,
            "total": len(results),
        }

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        url = self.BASE_URL + "/q.php?q={}&cat=0".format(quote(query))
        return await self._results(url, start_time)

    async def trending(self, category, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        url = self.BASE_URL + "/precompiled/data_top100_all.json"
        return await self._results(url, start_time)

    async def recent(self, category, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        url = self.BASE_URL + "/precompiled/data_top100_recent.json"
        return await self._results(url, start_time)
