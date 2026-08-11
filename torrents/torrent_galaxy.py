import asyncio
import math
import time
from datetime import datetime
from urllib.parse import quote

import aiohttp

from constants.base_url import TGX
from constants.headers import HEADER_AIO
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.trackers import build_magnet, build_torrent_url

PAGE_SIZE = 50

HOSTS = [TGX, "https://torrentgalaxy.one"]


def format_size(size):
    try:
        size = float(size)
    except (TypeError, ValueError):
        return str(size)
    if size <= 0:
        return "0"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return "{:.2f} {}".format(size, units[i])


def format_date(ts):
    try:
        return datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


class TorrentGalaxy:
    _name = "Torrent Galaxy"

    def __init__(self):
        self.BASE_URL = TGX
        self.LIMIT = None

    @staticmethod
    def _map_category(category):
        cat = (category or "").lower()
        if cat == "tv":
            return "TV"
        if cat == "xxx":
            return "XXX"
        if cat == "apps":
            return "Apps"
        if cat == "other":
            return "Other"
        return cat.capitalize() if cat else None

    @decorator_asyncio_fix
    async def _fetch(self, endpoint):
        # torrentgalaxy.info is behind Cloudflare and resets plain-TLS
        # connections, so each host is tried with a dedicated SSL connector.
        for host in HOSTS:
            url = host + endpoint
            for attempt in range(2):
                try:
                    async with aiohttp.ClientSession(
                        connector=aiohttp.TCPConnector(ssl=True),
                        connector_owner=False,
                    ) as session:
                        async with session.get(
                            url,
                            headers=HEADER_AIO,
                            timeout=aiohttp.ClientTimeout(total=20),
                        ) as res:
                            if res.status >= 400:
                                break
                            data = await res.json(content_type=None)
                            self.BASE_URL = host
                            return data
                except Exception:
                    await asyncio.sleep(0.5)
                    continue
        return None

    def _parse(self, data, page, start_time):
        results = []
        for item in data.get("results", []):
            name = item.get("n")
            if not name:
                continue
            info_hash = item.get("h") or ""
            pk = item.get("pk") or ""
            poster = item.get("t")
            if poster and poster.startswith("/"):
                poster = self.BASE_URL + poster
            results.append(
                {
                    "name": name,
                    "size": format_size(item.get("s")),
                    "date": format_date(item.get("a")),
                    "seeders": item.get("se"),
                    "leechers": item.get("le"),
                    "category": item.get("c"),
                    "uploader": item.get("u"),
                    "imdb_id": item.get("i"),
                    "hash": info_hash,
                    "magnet": build_magnet(info_hash, name) if info_hash else None,
                    "torrent": build_torrent_url(info_hash, name) if info_hash else None,
                    "url": "{}/post-detail/{}/".format(self.BASE_URL, pk) if pk else self.BASE_URL,
                    "poster": poster,
                }
            )
            if self.LIMIT and len(results) >= self.LIMIT:
                break
        total = data.get("total") or 0
        total_pages = math.ceil(total / PAGE_SIZE) if total else 1
        return {
            "data": results,
            "current_page": page,
            "total_pages": total_pages,
            "time": time.time() - start_time,
            "total": len(results),
        }

    async def _request(self, endpoint, page):
        if page > 1:
            endpoint += "?page={}".format(page)
        return await self._fetch(endpoint)

    async def search(self, query, page, limit):
        self.LIMIT = limit
        start_time = time.time()
        endpoint = "/get-posts/keywords:{}:format:json/".format(quote(query))
        data = await self._request(endpoint, page)
        if data is None:
            return None
        return self._parse(data, page, start_time)

    async def trending(self, category, page, limit):
        self.LIMIT = limit
        start_time = time.time()
        cat = self._map_category(category)
        if not cat:
            endpoint = "/get-posts/format:json/"
        else:
            endpoint = "/get-posts/category:{}:time:10D:format:json/".format(cat)
        data = await self._request(endpoint, page)
        if data is None:
            return None
        return self._parse(data, page, start_time)

    async def recent(self, category, page, limit):
        return await self.trending(category, page, limit)

    async def get_torrent_by_url(self, torrent_url):
        return None
