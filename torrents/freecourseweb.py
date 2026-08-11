import asyncio
import re
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import FREECOURSEWEB
from helper.trackers import build_torrent_url


class FreeCourseWeb:
    _name = "Free Course Web"

    def __init__(self):
        self.BASE_URL = FREECOURSEWEB
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                html = await Scraper().get_all_results(session, url)
                if not html or not html[0]:
                    return None
                m = re.search(r'href="(magnet:\?xt=[^"]+)"', html[0])
                if not m:
                    return None
                magnet = m.group(1)
                obj["magnet"] = magnet
                hm = re.search(r"([{a-f\d,A-F\d}]{32,40})\b", magnet)
                if hm:
                    obj["hash"] = hm.group(0)
                    obj["torrent"] = build_torrent_url(hm.group(0), obj.get("name") or "")
            except:
                return None

    async def _get_magnets(self, result, session, urls):
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

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                my_dict = {"data": []}
                for a in soup.select("h2.entry-title.post-title a[href]"):
                    name = a.get_text(" ", strip=True)
                    url = a["href"]
                    if url.startswith("/"):
                        url = self.BASE_URL + url
                    my_dict["data"].append({"name": name, "url": url})
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    page_nums = []
                    for a in soup.select('a[href*="/page/"]'):
                        m = re.search(r"/page/(\d+)/", a["href"])
                        if m:
                            page_nums.append(int(m.group(1)))
                    if page_nums:
                        my_dict["total_pages"] = max(page_nums)
                except:
                    ...
                return my_dict
        except:
            return None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
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

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            return await self._collect(
                session,
                lambda p: (
                    self.BASE_URL + "/tutorialsv4/page/{}/".format(p)
                    if p > 1
                    else self.BASE_URL + "/tutorialsv4/"
                ),
                page,
                start_time,
            )

    async def _collect(self, session, url_fn, page, start_time):
        all_data = []
        total_pages = page
        current = page
        while True:
            html = await Scraper().get_all_results(session, url_fn(current))
            results = self._parser(html)
            if results is None or len(results["data"]) == 0:
                break
            seen = {obj["url"] for obj in all_data}
            for obj in results["data"]:
                if obj["url"] not in seen:
                    all_data.append(obj)
            if results.get("total_pages"):
                total_pages = results["total_pages"]
            if len(all_data) >= self.LIMIT:
                break
            if current >= total_pages or current >= 25:
                break
            current += 1
        if not all_data:
            return None
        urls = [obj["url"] for obj in all_data]
        results = {"data": all_data}
        results = await self._get_magnets(results, session, urls)
        results["data"] = results["data"][0 : self.LIMIT]
        results["time"] = time.time() - start_time
        results["total"] = len(results["data"])
        results["current_page"] = page
        results["total_pages"] = total_pages
        return results
