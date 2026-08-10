import asyncio
import re
import time
import aiohttp
from urllib.parse import quote
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from constants.base_url import YTS
from constants.headers import HEADER_AIO

TRACKERS = [
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://9.rarbg.to:2710/announce",
    "udp://tracker.leechers-paradise.org:6969/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
]


class Yts:
    _name = "YTS"

    def __init__(self):
        self.BASE_URL = YTS
        self.LIMIT = None

    def _magnet(self, torrent_hash, title):
        magnet = "magnet:?xt=urn:btih:{}&dn={}".format(
            torrent_hash, quote(title)
        )
        for tracker in TRACKERS:
            magnet += "&tr=" + quote(tracker, safe=":/")
        return magnet

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
            magnet = self._magnet(torrent["hash"], name)
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
    async def _fetch_json(self, session, url, retries=3):
        for attempt in range(retries):
            try:
                async with session.get(
                    url,
                    headers=HEADER_AIO,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as res:
                    if res.status >= 400:
                        continue
                    return await res.json(content_type=None)
            except Exception:
                if attempt == retries - 1:
                    return None
                await asyncio.sleep(1)
        return None

    async def _get_movies(self, url, start_time):
        async with aiohttp.ClientSession() as session:
            data = await self._fetch_json(session, url)
            if data is None or data.get("status") != "ok":
                return None
            movies = (data.get("data") or {}).get("movies") or []
            result, urls = self._parse_movies(movies)
            result["time"] = time.time() - start_time
            result["total"] = len(result["data"])
            return result

    async def search(self, query, page, limit):
        self.LIMIT = limit
        start_time = time.time()
        url = "{}/api/v2/list_movies.json?query_term={}&page={}&limit={}".format(
            self.BASE_URL, quote(query), page, min(limit, 50)
        )
        return await self._get_movies(url, start_time)

    async def trending(self, category, page, limit):
        self.LIMIT = limit
        start_time = time.time()
        url = "{}/api/v2/list_movies.json?sort_by=download_count&order_by=desc&page={}&limit={}".format(
            self.BASE_URL, page, min(limit, 50)
        )
        return await self._get_movies(url, start_time)

    async def recent(self, category, page, limit):
        self.LIMIT = limit
        start_time = time.time()
        url = "{}/api/v2/list_movies.json?sort_by=date_added&order_by=desc&page={}&limit={}".format(
            self.BASE_URL, page, min(limit, 50)
        )
        return await self._get_movies(url, start_time)
