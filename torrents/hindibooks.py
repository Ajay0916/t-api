import asyncio
import html as html_lib
import re
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup

from constants.base_url import HINDIBOOKS
from constants.headers import HEADER_AIO, AIO_TIMEOUT
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper


class HindiBooks:
    _name = "Hindi Books"

    def __init__(self):
        self.BASE_URL = HINDIBOOKS
        self.LIMIT = None

    def _parser(self, htmls):
        try:
            for html in htmls:
                if not html:
                    continue
                soup = BeautifulSoup(html, "html.parser")
                my_dict = {"data": []}
                for a in soup.select("h2.entry-title a[href]"):
                    name = html_lib.unescape(a.get_text(" ", strip=True)).strip()
                    url = a["href"]
                    if not name or len(name) < 5:
                        continue
                    my_dict["data"].append({"name": name, "url": url})
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                return my_dict
        except Exception:
            return None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                html = await Scraper().get_all_results(session, url)
                if not html or not html[0]:
                    return None
                # Collect every file link on the post in priority order so
                # WZML gets a primary AND an alternate Direct Link (Google
                # Drive quota/503s don't kill the result when another host
                # exists on the same post).
                links = []
                am = re.search(
                    r'href="(https://archive\.org/download/[^"]+\.pdf)"', html[0]
                )
                if am:
                    links.append(am.group(1))
                zm = re.search(
                    r'href="(https://[^"]*zohoexternal[^"]+)"', html[0]
                )
                if zm:
                    links.append(zm.group(1).replace("&amp;", "&").replace(" ", "%20"))
                dm = re.search(
                    r'href="(https://[^"]*(?:drive\.usercontent\.google\.com|drive\.google\.com)[^"]+)"',
                    html[0],
                )
                if dm:
                    links.append(dm.group(1).replace("&amp;", "&").replace(" ", "%20"))
                bm = re.search(
                    r'href="(https://buy\.hindibook\.in/book\.php\?name=[^"]+)"',
                    html[0],
                )
                if bm:
                    links.append(bm.group(1).replace(" ", "%20"))
                qm = re.search(
                    r'href="(https://buy\.hindibook\.in/quick-download\.php\?ref=[^"]+)"',
                    html[0],
                )
                if qm:
                    links.append(qm.group(1).replace(" ", "%20"))
                if links:
                    obj["torrent"] = links[0]
                    if len(links) > 1:
                        obj["download"] = links[1]
                    if am:
                        obj["extension"] = "pdf"
                    else:
                        em = re.search(
                            r"\.(pdf|epub|mobi|azw3|djvu|fb2)(?:[?#]|$)",
                            links[0],
                            re.I,
                        )
                        if em:
                            obj["extension"] = em.group(1).lower()
                    try:
                        async with session.head(
                            links[0],
                            headers=HEADER_AIO,
                            timeout=AIO_TIMEOUT,
                            allow_redirects=True,
                        ) as r:
                            length = r.headers.get("Content-Length")
                            if length:
                                obj["size"] = self._format_size(int(length))
                    except Exception:
                        pass
                    if not obj.get("extension"):
                        em = re.search(
                            r"\b(PDF|EPUB|MOBI|AZW3|DJVU|FB2)\b",
                            obj.get("name") or "",
                            re.I,
                        )
                        if em:
                            obj["extension"] = em.group(1).lower()
            except Exception:
                return None

    @staticmethod
    def _format_size(num):
        if num >= 1024 ** 3:
            return "{:.2f} GB".format(num / 1024 ** 3)
        if num >= 1024 ** 2:
            return "{:.1f} MB".format(num / 1024 ** 2)
        return "{} KB".format(int(num / 1024))

    async def _get_links(self, result, session, urls):
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

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/search?q={}&max-results={}".format(
                quote(query), limit
            )
            html = await Scraper().get_all_results(session, url)
            results = self._parser(html)
            if results is None or len(results["data"]) == 0:
                return None
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            urls = [obj["url"] for obj in results["data"]]
            results = await self._get_links(results, session, urls)
            results["data"] = [
                d for d in results["data"] if d.get("torrent")
            ]
            results["total"] = len(results["data"])
            return results
