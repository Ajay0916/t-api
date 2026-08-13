import asyncio
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import AUDIOBOOKBAY
from constants.headers import HEADER_AIO
from helper.trackers import build_magnet

HOSTS = [AUDIOBOOKBAY]


class AudiobookBay:
    _name = "Audiobook Bay"

    def __init__(self):
        self.BASE_URL = AUDIOBOOKBAY
        self.LIMIT = None

    async def _fetch_page(self, session, path):
        for host in HOSTS:
            try:
                async with session.get(
                    host + path,
                    headers=HEADER_AIO,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as res:
                    if res.status >= 400:
                        continue
                    text = await res.text()
                if text:
                    self.BASE_URL = host
                    return [text]
            except Exception:
                continue
        return None

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
            except Exception:
                return None

    async def _get_torrent(self, result, session, urls):
        tasks = []
        sem = asyncio.Semaphore(6)
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(session, url, obj, sem)
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
                    authors = None
                    if " - " in name:
                        parts = [p.strip() for p in name.split(" - ") if p.strip()]
                        if len(parts) >= 2:
                            authors = [parts[-1]]
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
                            "authors": authors,
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
                except Exception:
                    ...
                return my_dict
        except Exception:
            return None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            path = "/search/{}/".format(quote(query))
            return await self.parser_result(
                start_time, path, session, page=page, query=query
            )

    def _parse_rss(self, xml_text, start_time):
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None
        data = []
        for item in root.iter("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            date_el = item.find("pubDate")
            name = title_el.text.strip() if title_el is not None and title_el.text else ""
            link = link_el.text.strip() if link_el is not None and link_el.text else ""
            if not name or not link:
                continue
            data.append(
                {
                    "name": name,
                    "size": "",
                    "category": "",
                    "date": date_el.text.strip() if date_el is not None and date_el.text else "",
                    "uploader": "",
                    "url": link,
                    "hash": None,
                    "magnet": None,
                }
            )
            if self.LIMIT and len(data) >= self.LIMIT:
                break
        if not data:
            return None
        return {
            "data": data,
            "current_page": 1,
            "total_pages": 1,
            "time": time.time() - start_time,
            "total": len(data),
        }

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            html = await self._fetch_page(session, "/feed/")
            if html is None:
                return None
            results = self._parse_rss(html[0], start_time)
            if results is None:
                return None
            urls = [item["url"] for item in results["data"]]
            results = await self._get_torrent(results, session, urls)
            results["data"] = results["data"][0 : self.LIMIT]
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results

    async def parser_result(self, start_time, path, session, page=1, query=None):
        html = await self._fetch_page(session, path)
        if html is None:
            return None
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
                    except Exception:
                        break
                    if page >= total_pages:
                        break
                    if page >= 25:
                        break
                    page += 1
                    path = "/search/{}/page/{}/".format(quote(query), page)
                    html = await self._fetch_page(session, path)
                    if html is None:
                        break
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
