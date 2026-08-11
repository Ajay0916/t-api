import asyncio
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import cloudscraper
from bs4 import BeautifulSoup

from constants.base_url import NINEXMOVIES
from helper.asyncioPoliciesFix import decorator_asyncio_fix


class NinexMovies:
    _name = "9xMovies"

    _executor = ThreadPoolExecutor(max_workers=8)
    _UA = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    _SKIP = (
        "wp-", "category", "search", "page", "tag", "author", "feed",
        "xmlrpc", "privacy", "dmca", "contact", "about", "terms", "how-to",
    )

    def __init__(self):
        self.BASE_URL = NINEXMOVIES
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
            r = self._get_scraper().get(url, headers=self._UA, timeout=25)
            if r.status_code >= 400:
                return []
            soup = BeautifulSoup(r.text, "html.parser")
            posts = {}
            for div in soup.find_all("div", class_=re.compile(r"\bthumb\b")):
                a = div.find("a", href=True)
                img = div.find("img")
                title = None
                if img:
                    title = img.get("title") or img.get("alt")
                if not title and a:
                    title = a.get_text(" ", strip=True)
                if not a or not title:
                    continue
                href = a["href"]
                if not href.startswith(self.BASE_URL):
                    continue
                path = href[len(self.BASE_URL):].strip("/")
                if not path or "/" in path or path.startswith(self._SKIP):
                    continue
                title = title.strip()
                if len(title) < 10:
                    continue
                posts[href] = title
            return [{"name": t, "url": u} for u, t in list(posts.items())[: self.LIMIT]]
        except:
            return []

    def _detail_links_sync(self, url):
        try:
            r = self._get_scraper().get(url, headers=self._UA, timeout=25)
            if r.status_code >= 400:
                return []
            html = r.text
            sizes = re.findall(
                r"(\d{3,4}p)\D{0,60}?\[\s*([\d.]+\s?(?:GB|MB))\]", html, re.I
            )
            links = list(
                dict.fromkeys(
                    re.findall(
                        r'href="(https://[a-z0-9.-]*linksddr[a-z0-9.-]*/view/[A-Za-z0-9]+)"',
                        html,
                    )
                )
            )
            out = []
            for idx, lk in enumerate(links):
                out.append(
                    {
                        "link": lk,
                        "size": sizes[idx][1] if idx < len(sizes) else None,
                    }
                )
            return out
        except:
            return []

    @staticmethod
    def _extract_hosts(html):
        hosts = re.findall(r'href="(https?://[^"]+)"', html)
        for h in hosts:
            if re.search(
                r"linksddr|favicon|\.css|\.js|/login|/register|/faqs|/contact|/money|/page/|/save/",
                h,
            ):
                continue
            return h
        return None

    def _unlock_sync(self, view_url):
        try:
            scraper = self._get_scraper()
            r = scraper.get(view_url, headers=self._UA, timeout=25)
            if r.status_code >= 400:
                return None
            m = re.search(
                r'name="(_csrf_token_[a-f0-9]+)" value="([a-f0-9]+)"', r.text
            )
            if not m:
                return None
            time.sleep(0.3)
            r = scraper.post(
                view_url, data={m.group(1): m.group(2)}, headers=self._UA, timeout=25
            )
            if r.status_code >= 400:
                return None
            host = self._extract_hosts(r.text)
            if host:
                return host
            final = r.url
            if final and final != view_url:
                time.sleep(0.3)
                r = scraper.get(final, headers=self._UA, timeout=25)
                m = re.search(
                    r'name="(_csrf_token_[a-f0-9]+)" value="([a-f0-9]+)"', r.text
                )
                if not m:
                    return None
                time.sleep(0.3)
                r = scraper.post(
                    final,
                    data={m.group(1): m.group(2)},
                    headers=self._UA,
                    timeout=25,
                )
                return self._extract_hosts(r.text)
            return None
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
                if links[0]["size"]:
                    obj["size"] = links[0]["size"]
                for item in links[:2]:
                    direct = await loop.run_in_executor(
                        self._executor, self._unlock_sync, item["link"]
                    )
                    if direct:
                        obj["torrent"] = direct
                        return None
            except:
                return None

    async def _get_links(self, result):
        tasks = []
        sem = asyncio.Semaphore(4)
        for item in result["data"]:
            tasks.append(asyncio.create_task(self._individual_scrap(item, sem)))
        await asyncio.gather(*tasks)
        return result

    @staticmethod
    def _matches_query(name, query):
        tokens = [t for t in re.split(r"\s+", query.lower()) if len(t) >= 2]
        if not tokens:
            return True
        title = re.sub(r"[^a-z0-9]+", "", name.lower())
        return all(t in title for t in tokens)

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        loop = asyncio.get_running_loop()
        posts = await loop.run_in_executor(
            self._executor, self._search_sync, query, page
        )
        if not posts:
            return None
        posts = [p for p in posts if self._matches_query(p["name"], query)]
        if not posts:
            return None
        results = {"data": []}
        for p in posts[: limit]:
            m = re.search(r"(\d+(?:\.\d+)?)\s?(GB|GiB|MB|MiB)", p["name"])
            p["size"] = "{}{}".format(m.group(1), m.group(2)) if m else "1GB"
            results["data"].append(p)
        results["time"] = time.time() - start_time
        results["total"] = len(results["data"])
        results = await self._get_links(results)
        results["data"] = [
            d
            for d in results["data"]
            if d.get("torrent") or d.get("magnet")
        ]
        results["total"] = len(results["data"])
        return results
