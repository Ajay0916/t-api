import asyncio
import json
import re
import time

import aiohttp
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import BOLLY4U
from constants.headers import HEADER_AIO


class Bolly4u:
    _name = "Bolly4u"

    _cache = None
    _cache_time = 0
    INDEX_TTL = 6 * 3600

    def __init__(self):
        self.BASE_URL = BOLLY4U
        self.INDEX_URL = self.BASE_URL + "/wp-content/uploads/search-index.json"
        self.LIMIT = None

    async def _fetch_index(self, session):
        now = time.time()
        if Bolly4u._cache and now - Bolly4u._cache_time < Bolly4u.INDEX_TTL:
            return Bolly4u._cache
        try:
            async with session.get(
                self.INDEX_URL,
                headers=HEADER_AIO,
                timeout=aiohttp.ClientTimeout(total=90),
            ) as r:
                if r.status >= 400:
                    return []
                items = json.loads(await r.text()).get("items", [])
            Bolly4u._cache = items
            Bolly4u._cache_time = now
            return items
        except:
            return []

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                html = await Scraper().get_all_results(session, url)
                if not html or not html[0]:
                    return None
                links = re.findall(
                    r'href="(https?://[^"]+/download/[A-Za-z0-9%:,_.\-]+)"', html[0]
                )
                if links:
                    obj["download"] = links[0]
            except:
                return None

    async def _get_download_links(self, result, session, urls):
        tasks = []
        sem = asyncio.Semaphore(6)
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(session, url, result["data"][idx], sem)
                    )
                    tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    def _parser(self, items, query):
        q = query.lower()
        my_dict = {"data": []}
        for it in items:
            name = (it.get("t") or "").strip()
            if not name or q not in name.lower():
                continue
            url = it.get("u")
            if not url:
                continue
            my_dict["data"].append({"name": name, "url": url})
            if len(my_dict["data"]) == self.LIMIT:
                break
        return my_dict

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            items = await self._fetch_index(session)
            if not items:
                return None
            results = self._parser(items, query)
            if len(results["data"]) == 0:
                return None
            start = (page - 1) * limit
            results["data"] = results["data"][start : start + limit]
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            urls = [obj["url"] for obj in results["data"]]
            results = await self._get_download_links(results, session, urls)
            results["total"] = len(results["data"])
            return results
