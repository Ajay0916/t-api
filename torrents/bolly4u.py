import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import cloudscraper
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from constants.base_url import BOLLY4U


class Bolly4u:
    _name = "Bolly4u"

    _cache = None
    _cache_time = 0
    INDEX_TTL = 6 * 3600
    _executor = ThreadPoolExecutor(max_workers=3)
    _UA = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }

    def __init__(self):
        self.BASE_URL = BOLLY4U
        self.INDEX_URL = self.BASE_URL + "/wp-content/uploads/search-index.json"
        self.LIMIT = None
        self._scraper = None

    def _get_scraper(self):
        if self._scraper is None:
            self._scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "desktop": True}
            )
        return self._scraper

    def _fetch_index_sync(self):
        try:
            r = self._get_scraper().get(self.INDEX_URL, headers=self._UA, timeout=120)
            if r.status_code >= 400:
                return []
            return json.loads(r.text).get("items", [])
        except:
            return []

    async def _fetch_index(self):
        now = time.time()
        if Bolly4u._cache and now - Bolly4u._cache_time < Bolly4u.INDEX_TTL:
            return Bolly4u._cache
        loop = asyncio.get_running_loop()
        items = await loop.run_in_executor(self._executor, self._fetch_index_sync)
        if items:
            Bolly4u._cache = items
            Bolly4u._cache_time = now
        return items

    def _detail_html(self, url):
        try:
            r = self._get_scraper().get(url, headers=self._UA, timeout=45)
            if r.status_code >= 400:
                return None
            return r.text
        except:
            return None

    def _resolve_download_sync(self, dl_url):
        try:
            scraper = self._get_scraper()
            r = scraper.get(dl_url, headers=self._UA, timeout=45)
            if r.status_code >= 400:
                return None
            html = r.text
            uid = re.search(r'data-uid="([^"]+)"', html)
            tok = re.search(r'data-token="([^"]+)"', html)
            if not uid or not tok:
                return None
            time.sleep(1.5)
            base = urlsplit(dl_url)
            action = "{}://{}/action".format(base.scheme, base.netloc)
            headers = {
                **self._UA,
                "Content-Type": "application/json; charset=UTF-8",
                "X-Requested-With": "xmlhttprequest",
                "Cache-Control": "no-cache",
            }
            r = scraper.post(
                action,
                json={
                    "type": "DOWNLOAD_GENERATE",
                    "payload": {"uid": uid.group(1), "access_token": tok.group(1)},
                },
                headers=headers,
                timeout=45,
            )
            if r.status_code >= 400:
                return None
            data = r.json()
            return data.get("download_url")
        except:
            return None

    @decorator_asyncio_fix
    async def _individual_scrap(self, url, obj, sem):
        async with sem:
            try:
                loop = asyncio.get_running_loop()
                html = await loop.run_in_executor(
                    self._executor, self._detail_html, url
                )
                if not html:
                    return None
                links = re.findall(
                    r'href="(https?://[^"]+/download/[A-Za-z0-9%:,_.\-]+)"', html
                )
                if not links:
                    return None
                for link in links[:3]:
                    direct = await loop.run_in_executor(
                        self._executor, self._resolve_download_sync, link
                    )
                    if direct:
                        obj["download"] = direct
                        break
            except:
                return None

    async def _get_download_links(self, result, urls):
        tasks = []
        sem = asyncio.Semaphore(1)
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(url, result["data"][idx], sem)
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
        start_time = time.time()
        self.LIMIT = limit
        items = await self._fetch_index()
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
        results = await self._get_download_links(results, urls)
        results["total"] = len(results["data"])
        return results
