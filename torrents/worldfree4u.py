import asyncio
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlsplit

import cloudscraper
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from constants.base_url import WORLDFREE4U


class WorldFree4u:
    _name = "WorldFree4u"

    _executor = ThreadPoolExecutor(max_workers=3)
    _UA = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }

    def __init__(self):
        self.BASE_URL = WORLDFREE4U
        self.LIMIT = None
        self._scraper = None

    def _get_scraper(self):
        if self._scraper is None:
            self._scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "desktop": True}
            )
        return self._scraper

    def _search_sync(self, query, page):
        try:
            url = self.BASE_URL + "/?s=" + quote(query)
            if page > 1:
                url = self.BASE_URL + "/page/{}/?s=".format(page) + quote(query)
            r = self._get_scraper().get(url, headers=self._UA, timeout=45)
            if r.status_code >= 400:
                return []
            soup = BeautifulSoup(r.text, "html.parser")
            posts = {}
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith(self.BASE_URL):
                    continue
                path = href[len(self.BASE_URL):].strip("/")
                if not path or "/" in path:
                    continue
                if path.startswith(
                    ("wp-", "category", "search", "page", "tag", "author", "feed", "xmlrpc", "privacy", "dmca", "contact", "about", "terms")
                ):
                    continue
                title = a.get_text(" ", strip=True)
                if not title or not any(c.isalnum() for c in title):
                    continue
                if len(title) < 10:
                    continue
                posts[href] = title
            return [{"name": t, "url": u} for u, t in list(posts.items())[: self.LIMIT]]
        except:
            return []

    def _detail_links_sync(self, url):
        try:
            r = self._get_scraper().get(url, headers=self._UA, timeout=45)
            if r.status_code >= 400:
                return []
            html = r.text
            links = re.findall(
                r'href="(https?://[^"]+/1zCCLabopUythxAW/[^"]+)"', html
            )
            if not links:
                links = re.findall(r'href="(https?://[^"]+/download/[^"]+)"', html)
            return links
        except:
            return []

    def _host_page_sync(self, url):
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

    def _save_magnet_sync(self, url):
        try:
            r = self._get_scraper().get(url, headers=self._UA, timeout=45)
            if r.status_code >= 400:
                return None
            m = re.search(r'href="(magnet:\?xt=[^"]+)"', r.text)
            return m.group(1) if m else None
        except:
            return None

    @decorator_asyncio_fix
    async def _individual_scrap(self, obj, sem):
        async with sem:
            try:
                loop = asyncio.get_running_loop()
                links = await loop.run_in_executor(
                    self._executor, self._detail_links_sync, obj["url"]
                )
                if not links:
                    return None
                for lk in links[:3]:
                    html = await loop.run_in_executor(
                        self._executor, self._host_page_sync, lk
                    )
                    if not html:
                        continue
                    dl = re.search(
                        r'href="(https?://[^"]+/download/[A-Za-z0-9%:,_.\-]+)"', html
                    )
                    if dl:
                        direct = await loop.run_in_executor(
                            self._executor, self._resolve_download_sync, dl.group(1)
                        )
                        if direct:
                            obj["torrent"] = direct
                            return None
                    save = re.search(r'href="(https?://[^"]+/save/[A-Za-z0-9]+)"', html)
                    if save:
                        magnet = await loop.run_in_executor(
                            self._executor, self._save_magnet_sync, save.group(1)
                        )
                        if magnet:
                            obj["magnet"] = magnet
                            return None
            except:
                return None

    async def _get_links(self, result):
        tasks = []
        sem = asyncio.Semaphore(1)
        for idx in range(len(result["data"])):
            task = asyncio.create_task(
                self._individual_scrap(result["data"][idx], sem)
            )
            tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        loop = asyncio.get_running_loop()
        posts = await loop.run_in_executor(
            self._executor, self._search_sync, query, page
        )
        if not posts:
            return None
        results = {"data": []}
        for p in posts:
            m = re.search(r"(\d+(?:\.\d+)?)\s?(GB|GiB|MB|MiB)", p["name"])
            p["size"] = "{}{}".format(m.group(1), m.group(2)) if m else "1GB"
            results["data"].append(p)
        results["time"] = time.time() - start_time
        results["total"] = len(results["data"])
        results = await self._get_links(results)
        results["total"] = len(results["data"])
        return results
