import asyncio
import os
import re
import time
from urllib.parse import quote

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup

from constants.base_url import ANNASAARCHIVE
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.author_utils import clean_archive_creators
from helper.html_scraper import Scraper


class AnnasArchive:
    _name = "Anna's Archive"

    MIRRORS = [
        "https://annas-archive.gl",
        "https://annas-archive.pk",
        "https://annas-archive.gd",
    ]

    def __init__(self):
        self.BASE_URL = ANNASAARCHIVE
        self.LIMIT = None
        self._UA = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
            )
        }

    def _parser(self, html):
        try:
            soup = BeautifulSoup(html, "html.parser")
            out = []
            for c in soup.select("div.flex.pt-3.pb-3.border-b"):
                a = c.select_one("a.js-vim-focus")
                if not a or not a.get("href"):
                    continue
                href = a["href"].strip()
                m = re.match(r"/md5/([a-f0-9]{32})", href)
                if not m:
                    continue
                name = a.get_text(" ", strip=True)
                if not name:
                    continue
                author = None
                nxt = a.find_next_sibling("a")
                if nxt and nxt.get("href", "").startswith("/search?q="):
                    author = nxt.get_text(" ", strip=True)
                info = c.select_one("div.text-gray-800")
                info_text = info.get_text(" ", strip=True) if info else ""
                out.append(
                    {
                        "name": name,
                        "authors": clean_archive_creators(author),
                        "md5": m.group(1),
                        "info": info_text,
                    }
                )
                if len(out) == self.LIMIT:
                    break
            return out
        except Exception:
            return []

    def _parse_info(self, obj):
        info = obj.get("info") or ""
        lang = re.search(r"([A-Za-z ]+?)\s*\[[a-z]{2}\]", info)
        if lang:
            obj["language"] = lang.group(1).strip()
        ext = re.search(r"·\s*(PDF|EPUB|MOBI|AZW3|DJVU|FB2|TXT)\b", info, re.I)
        if ext:
            obj["extension"] = ext.group(1).upper()
        size = re.search(r"(\d+(?:\.\d+)?\s?(?:MB|GB|KB))\b", info, re.I)
        if size:
            obj["size"] = size.group(1)
        year = re.search(r"·\s*(19\d{2}|20\d{2})\b", info)
        if year:
            obj["year"] = year.group(1)

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, obj, sem):
        async with sem:
            try:
                html = await Scraper().get_all_results(
                    session,
                    "https://libgen.li/ads.php?md5=" + obj["md5"],
                )
                if not html or not html[0]:
                    return None
                m = re.search(
                    r'href="(get\.php\?md5=[a-f0-9]{32}&key=[A-Z0-9]+)"',
                    html[0],
                )
                if not m:
                    return None
                obj["torrent"] = "https://libgen.li/" + m.group(1)
                obj["url"] = self.BASE_URL + "/md5/" + obj["md5"]
                self._parse_info(obj)
            except Exception:
                return None

    async def _get_links(self, result, session):
        tasks = []
        sem = asyncio.Semaphore(4)
        for idx in range(len(result["data"])):
            tasks.append(
                asyncio.create_task(
                    self._individual_scrap(session, result["data"][idx], sem)
                )
            )
        await asyncio.gather(*tasks)
        return result

    async def _search_once(self, session, mirror, query, page):
        url = mirror + "/search?q=" + quote(query)
        if page > 1:
            url += "&page={}".format(page)
        try:
            html = await Scraper().get_all_results(session, url)
            if not html or not html[0]:
                return []
            return self._parser(html[0])
        except Exception:
            return []

    async def _flare_search_once(self, query, page):
        url = self.BASE_URL + "/search?q=" + quote(query)
        if page > 1:
            url += "&page={}".format(page)
        try:
            payload = {"cmd": "request.get", "url": url, "maxTimeout": 20000}
            async with aiohttp.ClientSession(
                connector=get_connector(), connector_owner=False, trust_env=True
            ) as session:
                async with session.post(
                    f"{FLARESOLVERR_URL}/v1", json=payload,
                    timeout=aiohttp.ClientTimeout(total=25),
                ) as res:
                    data = await res.json(content_type=None)
            solution = data.get("solution") or {}
            html = solution.get("response") or ""
            if solution.get("status") != 200 or "js-vim-focus" not in html:
                return []
            return self._parser(html)
        except Exception:
            return []

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True, timeout=timeout) as session:
            posts = []
            mirrors = [self.BASE_URL] + [
                m for m in self.MIRRORS if m != self.BASE_URL
            ]
            for mirror in mirrors:
                posts = await self._search_once(session, mirror, query, page)
                if posts:
                    break
            if not posts:
                posts = await self._flare_search_once(query, page)
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
