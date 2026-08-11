import asyncio
import re
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import AUDIOBOOKBAY
from helper.trackers import build_magnet


class AudiobookBay:
    _name = "Audiobook Bay"

    def __init__(self):
        self.BASE_URL = AUDIOBOOKBAY
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                html = await Scraper().get_all_results(session, url)
                if not html or not html[0]:
                    return None
                m = re.search(
                    r"Info Hash:\s*</td>\s*<td>([A-Fa-f0-9]{40})", html[0]
                )
                if m:
                    info_hash = m.group(1)
                    obj["hash"] = info_hash
                    obj["magnet"] = build_magnet(info_hash, obj.get("name") or "")
            except:
                return None

    async def _get_torrent(self, result, session, urls):
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
                for post in soup.select("div.post"):
                    h = post.select_one(".postTitle a")
                    if not h:
                        continue
                    name = h.get_text(" ", strip=True)
                    url = h["href"]
                    if url.startswith("/"):
                        url = self.BASE_URL + url
                    size = ""
                    category = ""
                    date = ""
                    info = post.select_one(".postInfo")
                    if info:
                        text = info.get_text("\n", strip=True)
                        m = re.search(r"Category:\s*([^\n]+)", text)
                        if m:
                            category = re.sub(r"\s+", " ", m.group(1)).strip()
                    content = post.select_one(".postContent")
                    if content:
                        text = content.get_text("\n", strip=True)
                        m = re.search(
                            r"File Size:\s*([\d.,]+\s*(?:GBs?|MBs?|KBs?|GiB|MiB))",
                            text,
                            re.I,
                        )
                        if m:
                            size = re.sub(r"\s+", " ", m.group(1)).strip()
                        m = re.search(r"Posted:\s*([^\n]+)", text)
                        if m:
                            date = m.group(1).strip()
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": size,
                            "category": category,
                            "date": date,
                            "uploader": "",
                            "url": url,
                            "hash": None,
                            "magnet": None,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    page_nums = []
                    for a in soup.select('a[href*="page/"]'):
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
            url = self.BASE_URL + "/?s={}".format(quote(query))
            return await self.parser_result(
                start_time, url, session, page=page, query=query
            )

    async def parser_result(self, start_time, url, session, page=1, query=None):
        html = await Scraper().get_all_results(session, url)
        results = self._parser(html)
        if results is not None:
            urls = [item["url"] for item in results["data"]]
            results = await self._get_torrent(results, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            if query is not None:
                results["current_page"] = page
                while len(results["data"]) < self.LIMIT:
                    try:
                        total_pages = results.get("total_pages", page)
                    except:
                        break
                    if page >= total_pages:
                        break
                    if page >= 25:
                        break
                    page += 1
                    url = self.BASE_URL + "/page/{}/?s={}".format(
                        page, quote(query)
                    )
                    html = await Scraper().get_all_results(session, url)
                    res = self._parser(html)
                    if res is None or len(res["data"]) == 0:
                        break
                    urls = [item["url"] for item in res["data"]]
                    res = await self._get_torrent(res, session, urls)
                    for obj in res["data"]:
                        results["data"].append(obj)
                    results["current_page"] = page
                    if res.get("total_pages"):
                        results["total_pages"] = res["total_pages"]
                    results["time"] = time.time() - start_time
                    results["total"] = len(results["data"])
                results["data"] = results["data"][0 : self.LIMIT]
                results["total"] = len(results["data"])
            return results
        return results
