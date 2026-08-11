import asyncio
import re
import time
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from constants.base_url import PDFDRIVE
from helper.asyncioPoliciesFix import decorator_asyncio_fix


class PdfDrive:
    _name = "PDFDrive"

    def __init__(self):
        self.BASE_URL = PDFDRIVE
        self.LIMIT = None
        self._UA = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
            ),
            "Referer": "https://pdfdrive.com.co/",
        }

    async def _fetch(self, session, url, retries=2):
        for attempt in range(retries):
            try:
                async with session.get(
                    url, headers=self._UA, allow_redirects=True
                ) as r:
                    if r.status >= 400:
                        return None
                    return await r.text()
            except:
                if attempt == retries - 1:
                    return None
                await asyncio.sleep(1)
        return None

    def _parser(self, html):
        try:
            soup = BeautifulSoup(html, "html.parser")
            out = []
            for panel in soup.select("div.bav.bav1"):
                a = panel.select_one("a[href]")
                if not a:
                    continue
                href = a["href"].strip()
                if not href.startswith(self.BASE_URL):
                    continue
                name = a.get("title") or a.get_text(" ", strip=True)
                if not name:
                    continue
                out.append({"name": name, "url": href})
                if len(out) == self.LIMIT:
                    break
            return out
        except:
            return []

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, obj, sem):
        async with sem:
            try:
                html = await self._fetch(
                    session, obj["url"] + "?download=links&opt=1"
                )
                if not html:
                    return None
                soup = BeautifulSoup(html, "html.parser")
                lnk = soup.select_one("ul#list-downloadlinks a[href]")
                if not lnk:
                    return None
                link = urljoin(self.BASE_URL, lnk["href"].strip())
                obj["torrent"] = link
                ext = re.search(r"\.([A-Za-z0-9]{3,5})$", link)
                if ext:
                    obj["extension"] = ext.group(1).upper()
                for th in soup.select("th"):
                    if th.get_text(strip=True).lower() == "size":
                        td = th.find_next("td")
                        if td:
                            size = td.get_text(" ", strip=True)
                            if size:
                                obj["size"] = size
                        break
            except:
                return None

    async def _get_links(self, result, session):
        tasks = []
        sem = asyncio.Semaphore(6)
        for idx in range(len(result["data"])):
            tasks.append(
                asyncio.create_task(
                    self._individual_scrap(session, result["data"][idx], sem)
                )
            )
        await asyncio.gather(*tasks)
        return result

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            q = query.replace(" ", "+")
            if page > 1:
                url = self.BASE_URL + "/page/{}/?s=".format(page) + q
            else:
                url = self.BASE_URL + "/?s=" + q
            html = await self._fetch(session, url)
            if not html:
                return None
            posts = self._parser(html)
            if not posts:
                return None
            results = {"data": posts}
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            results = await self._get_links(results, session)
            results["data"] = [
                d for d in results["data"] if d.get("torrent")
            ]
            results["total"] = len(results["data"])
            return results
