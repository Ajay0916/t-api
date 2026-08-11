import asyncio
import re
import time
import aiohttp
from helper.session import get_connector
from urllib.parse import quote
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from constants.base_url import YTS
from constants.headers import HEADER_AIO, AIO_TIMEOUT
from helper.trackers import build_magnet

HOSTS = [YTS, "https://yts.rs"]


class Yts:
    _name = "YTS"

    def __init__(self):
        self.BASE_URL = YTS
        self.LIMIT = None

    def _parse_movies(self, movies):
        my_dict = {"data": []}
        list_of_urls = []
        for movie in movies:
            torrents = movie.get("torrents") or []
            torrent = max(
                torrents,
                key=lambda t: (t.get("seeds") or 0),
                default=None,
            )
            if not torrent:
                continue
            name = movie.get("title_long") or movie.get("title")
            magnet = build_magnet(torrent["hash"], name)
            url = movie.get("url")
            list_of_urls.append(url)
            my_dict["data"].append(
                {
                    "name": name,
                    "size": torrent.get("size"),
                    "seeders": torrent.get("seeds"),
                    "leechers": torrent.get("peers"),
                    "category": "Movies",
                    "quality": torrent.get("quality"),
                    "year": movie.get("year"),
                    "rating": movie.get("rating"),
                    "hash": torrent["hash"],
                    "magnet": magnet,
                    "torrent": torrent.get("url"),
                    "url": url,
                }
            )
            if len(my_dict["data"]) == self.LIMIT:
                break
        return my_dict, list_of_urls

    @decorator_asyncio_fix
    async def _fetch_json(self, url, retries=2):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            for attempt in range(retries):
                try:
                    async with session.get(
                        url,
                        headers=HEADER_AIO,
                        timeout=AIO_TIMEOUT,
                        allow_redirects=True,
                    ) as res:
                        if res.status >= 400:
                            continue
                        return await res.json(content_type=None)
                except Exception:
                    if attempt == retries - 1:
                        return None
                    await asyncio.sleep(1)
            return None

    async def _get_movies(self, params, start_time):
        for base in HOSTS:
            data = await self._fetch_json("{}/api/v2/{}".format(base, params))
            if data is None or data.get("status") != "ok":
                continue
            self.BASE_URL = base
            movies = (data.get("data") or {}).get("movies") or []
            result, urls = self._parse_movies(movies)
            result["time"] = time.time() - start_time
            result["total"] = len(result["data"])
            return result
        return None

    async def search(self, query, page, limit):
        self.LIMIT = limit
        start_time = time.time()
        params = "list_movies.json?query_term={}&page={}&limit={}".format(
            quote(query), page, min(limit, 50)
        )
        return await self._get_movies(params, start_time)

    async def trending(self, category, page, limit):
        self.LIMIT = limit
        start_time = time.time()
        params = "list_movies.json?sort_by=download_count&order_by=desc&page={}&limit={}".format(
            page, min(limit, 50)
        )
        return await self._get_movies(params, start_time)

    async def recent(self, category, page, limit):
        self.LIMIT = limit
        start_time = time.time()
        params = "list_movies.json?sort_by=date_added&order_by=desc&page={}&limit={}".format(
            page, min(limit, 50)
        )
        return await self._get_movies(params, start_time)
