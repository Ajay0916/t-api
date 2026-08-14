import asyncio
import re
import time
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from constants.base_url import FREECOURSESITES
from constants.headers import HEADER_AIO
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.session import get_connector


class FreeCourseSites:
    _name = "Free Course Sites"

    def __init__(self):
        self.BASE_URL = FREECOURSESITES
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _get_page(self, session, url):
        try:
            async with session.get(
                url, headers=HEADER_AIO, timeout=aiohttp.ClientTimeout(total=15)
            ) as res:
                if res.status != 200:
                    return None
                return await res.text(errors="replace")
        except Exception:
            return None

    async def _page_info(self, session, url, sem):
        async with sem:
            html = await self._get_page(session, url)
            if not html:
                return None
            m = re.search(
                r'<a[^>]+class="mks_button[^"]*"[^>]*href="([^"]+)"', html
            )
            if not m:
                return None
            link = m.group(1).replace("&#038;", "&").replace("&amp;", "&")
            if not re.search(r"drive\.(?:usercontent\.)?google\.com/", link):
                return None
            return link

    async def _enrich(self, session, results):
        tasks = []
        sem = asyncio.Semaphore(6)
        for obj in results["data"]:
            tasks.append(
                asyncio.create_task(self._page_info(session, obj["url"], sem))
            )
        links = await asyncio.gather(*tasks)
        out = []
        for obj, link in zip(results["data"], links):
            if link:
                obj["torrent"] = link
                obj["download"] = link
                out.append(obj)
        results["data"] = out
        return results

    def _parser(self, html):
        try:
            soup = BeautifulSoup(html, "html.parser")
            my_dict = {"data": []}
            for a in soup.select("h2.entry-title a[href]"):
                name = a.get_text(" ", strip=True)
                url = a["href"]
                if url.startswith("/"):
                    url = self.BASE_URL + url
                if not name or not url.startswith("http"):
                    continue
                my_dict["data"].append({"name": name, "url": url})
                if self.LIMIT and len(my_dict["data"]) >= self.LIMIT * 3:
                    break
            page_nums = []
            for a in soup.select('a[href*="/page/"]'):
                m = re.search(r"/page/(\d+)/", a.get("href", ""))
                if m:
                    page_nums.append(int(m.group(1)))
            if page_nums:
                my_dict["total_pages"] = max(page_nums)
            return my_dict
        except Exception:
            return None

    async def _collect(self, session, url_fn, page, start_time):
        all_data = []
        total_pages = page
        current = page
        while True:
            html = await self._get_page(session, url_fn(current))
            results = self._parser(html) if html else None
            if results is None or not results["data"]:
                break
            if results.get("total_pages"):
                total_pages = results["total_pages"]
            seen = {obj["url"] for obj in all_data}
            for obj in results["data"]:
                if obj["url"] not in seen:
                    all_data.append(obj)
            if self.LIMIT and len(all_data) >= self.LIMIT * 3:
                break
            if current >= total_pages or current >= 25:
                break
            current += 1
        if not all_data:
            return None
        results = {"data": all_data}
        results = await self._enrich(session, results)
        if not results["data"]:
            return None
        results["data"] = results["data"][0 : self.LIMIT]
        results["time"] = time.time() - start_time
        results["total"] = len(results["data"])
        results["current_page"] = page
        results["total_pages"] = total_pages
        return results

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        async with aiohttp.ClientSession(
            connector=get_connector(), connector_owner=False, trust_env=True
        ) as session:
            return await self._collect(
                session,
                lambda p: (
                    self.BASE_URL + "/page/{}/?s={}".format(p, quote(query))
                    if p > 1
                    else self.BASE_URL + "/?s={}".format(quote(query))
                ),
                page,
                start_time,
            )
