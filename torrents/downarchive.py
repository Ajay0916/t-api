import asyncio
import re
import time
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from constants.base_url import DOWNARCHIVE
from constants.headers import HEADER_AIO, AIO_TIMEOUT
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.search_cache import TTLCache
from helper.session import get_connector


class DownArchive:
    _name = "Downarchive"
    _detail_cache = TTLCache(max_size=1024, ttl=21600, name="downarchive_detail")

    def __init__(self):
        self.BASE_URL = DOWNARCHIVE
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _get_page(self, session, url, retries=3):
        for attempt in range(retries):
            try:
                async with session.get(url, headers=HEADER_AIO, timeout=AIO_TIMEOUT) as res:
                    html = await res.text(errors="replace")
                if "MySQL Error" in html or "MySQL error" in html:
                    if attempt < retries - 1:
                        await asyncio.sleep(2)
                        continue
                    return None
                return html
            except Exception:
                if attempt < retries - 1:
                    await asyncio.sleep(2)
                    continue
        return None

    async def _page_info(self, session, url, sem):
        async with sem:
            try:
                html = await self._get_page(session, url)
                if not html:
                    return None, None
                size = None
                text = re.sub(r"<[^>]+>", " ", html)
                m = re.search(r"Size\s*[:\u2013\u2014\u2192-]?\s*([\d.,]+\s*(?:MB|GB|KB))\b", text, re.I)
                if not m:
                    m = re.search(r"([\d.,]+\s*(?:GB|MB|KB))\b", text)
                if m:
                    size = m.group(1).replace(" ", "")
                link = None
                for a in re.finditer(r'href="(https?://[^"]+)"', html):
                    href = a.group(1)
                    if re.search(r"(nitroflare\.com/view/|uploadgig\.com/file/download/|rapidgator\.net/file/)", href):
                        link = href
                        break
                if size or link:
                    self._detail_cache.set(url, {"size": size, "link": link})
                return size, link
            except Exception:
                return None, None

    async def _enrich(self, session, results):
        tasks = []
        pending_objs = []
        sem = asyncio.Semaphore(10)
        hits = 0
        for obj in results["data"]:
            cached = self._detail_cache.get(obj["url"])
            if cached:
                hits += 1
                if cached.get("size"):
                    obj["size"] = cached["size"]
                if cached.get("link"):
                    obj["torrent"] = cached["link"]
                    obj["download"] = cached["link"]
            else:
                pending_objs.append(obj)
                tasks.append(asyncio.create_task(self._page_info(session, obj["url"], sem)))
        infos = await asyncio.gather(*tasks)
        for obj, (size, link) in zip(pending_objs, infos):
            if size:
                obj["size"] = size
            if link:
                obj["torrent"] = link
                obj["download"] = link
        return results

    def _parser(self, html):
        try:
            soup = BeautifulSoup(html, "html.parser")
            my_dict = {"data": []}
            for div in soup.select("div.shortnews"):
                h1 = div.select_one("h1.ntitle")
                link = h1.select_one("a[href]") if h1 else None
                if not link:
                    continue
                name = link.get_text(" ", strip=True)
                url = link["href"]
                if not name or not url.startswith("http"):
                    continue
                cat = h1.select_one("span.cat")
                obj = {
                    "name": name,
                    "url": url,
                    "category": cat.get_text(" ", strip=True) if cat else "Video Training",
                    "hash": None,
                    "magnet": None,
                }
                meta = div.select_one("p.links")
                if meta:
                    m = re.search(r"Published by:\s*\S+\s*on\s*(\d{1,2})-(\d{1,2})-(\d{4})", meta.get_text(" ", strip=True))
                    if m:
                        dd, mm, yyyy = m.groups()
                        obj["date"] = "{}-{:02d}-{:02d}".format(yyyy, int(mm), int(dd))
                    u = meta.select_one("a[href*='/user/']")
                    if u:
                        obj["uploader"] = u.get_text(" ", strip=True)
                my_dict["data"].append(obj)
                if len(my_dict["data"]) == self.LIMIT:
                    break
            return my_dict
        except Exception:
            return None

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        url = self.BASE_URL + "/index.php?do=search&subaction=search&story={}&search_start={}&full_search=0".format(
            quote(query), max(page, 1)
        )
        async with aiohttp.ClientSession(
            connector=get_connector(), connector_owner=False, trust_env=True
        ) as session:
            html = await self._get_page(session, url)
            results = self._parser(html) if html else None
            if results is None or not results["data"]:
                return None
            results = await self._enrich(session, results)
            results["data"] = results["data"][0 : limit]
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            results["current_page"] = page
            results["total_pages"] = page
            return results


DownArchive._detail_cache.load()
