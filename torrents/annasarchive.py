import os
import time

import aiohttp

from constants.base_url import ANNASAARCHIVE


class AnnasArchive:
    _name = "Anna's Archive"

    def __init__(self):
        self.BASE_URL = ANNASAARCHIVE
        self.LIMIT = None
        self._key = os.environ.get("RAPIDAPI_KEY")
        self._host = os.environ.get(
            "RAPIDAPI_HOST", "annas-archive-api.p.rapidapi.com"
        )
        self._dl_base = os.environ.get(
            "ANNAS_DOWNLOAD_BASE", "http://132.145.136.242:8009"
        ).rstrip("/")

    def _headers(self):
        return {
            "x-rapidapi-key": self._key,
            "x-rapidapi-host": self._host,
        }

    @staticmethod
    def _format_size(num):
        try:
            num = int(num)
        except (TypeError, ValueError):
            return None
        if not num:
            return None
        if num >= 1024 ** 3:
            return "{:.2f} GB".format(num / 1024 ** 3)
        if num >= 1024 ** 2:
            return "{:.1f} MB".format(num / 1024 ** 2)
        return "{} KB".format(int(num / 1024))

    async def search(self, query, page, limit):
        if not self._key:
            return None
        start_time = time.time()
        self.LIMIT = limit
        params = {
            "q": query,
            "skip": max(0, (page - 1) * limit),
            "limit": limit,
            "sort": "mostRelevant",
            "cat": "fiction, nonfiction",
            "ext": "pdf, epub, mobi, azw3",
            "source": "libgenLi, libgenRs, zLibrary",
        }
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(
                    self.BASE_URL + "/search",
                    params=params,
                    headers=self._headers(),
                ) as r:
                    if r.status >= 400:
                        return None
                    data = await r.json()
            except:
                return None
        hits = data.get("hits") or []
        if not hits:
            return None
        results = {"data": []}
        for h in hits:
            md5 = (h.get("md5") or "").strip()
            title = (h.get("title") or "").strip()
            if not md5 or not title:
                continue
            results["data"].append(
                {
                    "name": title,
                    "author": h.get("author"),
                    "publisher": h.get("publisher"),
                    "year": h.get("year"),
                    "language": h.get("language"),
                    "extension": h.get("extension"),
                    "size": self._format_size(h.get("filesize")),
                    "hash": md5,
                    "torrent": self._dl_base + "/api/v1/download/annas?md5=" + md5,
                    "url": "https://annas-archive.is/search?q=" + md5,
                }
            )
        results["time"] = time.time() - start_time
        results["total"] = len(results["data"])
        return results
