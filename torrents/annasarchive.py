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
        "https://annas-archive.is",
        "https://annas-archive.se",
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
            for c in soup.select("div.bg-white.rounded-lg.shadow.p-4.mb-4"):
                a = c.select_one("h3 a")
                if not a or not a.get("href"):
                    continue
                href = a["href"].strip()
                if "/books/" not in href:
                    continue
                name = a.get_text(" ", strip=True)
                if not name:
                    continue
                info_el = c.select_one("div.text-sm.text-\\[\\#666\\].mt-1")
                info = info_el.get_text(" ", strip=True) if info_el else ""
                parts = [p.strip() for p in info.split("·")]
                author = parts[0] if parts else ""
                year = next(
                    (p for p in parts if re.fullmatch(r"(?:19|20)\d{2}", p)),
                    None,
                )
                ext = next(
                    (
                        p
                        for p in parts
                        if p.upper()
                        in ("PDF", "EPUB", "MOBI", "AZW3", "DJVU", "FB2", "TXT")
                    ),
                    None,
                )
                size = next(
                    (
                        p
                        for p in parts
                        if re.search(r"\d+(?:\.\d+)?\s?(?:MB|GB|KB)", p, re.I)
                    ),
                    None,
                )
                out.append(
                    {
                        "name": name,
                        "authors": clean_archive_creators(author),
                        "url": href,
                        "info": info,
                        "year": year,
                        "extension": ext,
                        "size": size,
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
        if not obj.get("extension"):
            ext = re.search(r"·\s*(PDF|EPUB|MOBI|AZW3|DJVU|FB2|TXT)\b", info, re.I)
            if ext:
                obj["extension"] = ext.group(1).upper()
        if not obj.get("size"):
            size = re.search(r"(\d+(?:\.\d+)?\s?(?:MB|GB|KB))\b", info, re.I)
            if size:
                obj["size"] = size.group(1)
        if not obj.get("year"):
            year = re.search(r"·\s*(19\d{2}|20\d{2})\b", info)
            if year:
                obj["year"] = year.group(1)

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, obj, sem):
        async with sem:
            try:
                # Anna's Archive moved download links (and the md5) behind
                # login, but the item page still exposes the ISBN in JSON-LD.
                # Resolve the download link through libgen.li instead: ISBN
                # search -> md5 -> ads.php -> get.php (same chain the Libgen
                # site uses, verified working anonymously).
                html = await Scraper().get_all_results(session, obj["url"])
                if not html or not html[0]:
                    return None
                md5 = None
                m = re.search(r'"isbn"\s*:\s*"([^"]+)"', html[0])
                if m:
                    for isbn in (i.strip() for i in m.group(1).split(",")):
                        if not isbn:
                            continue
                        html2 = await Scraper().get_all_results(
                            session,
                            "https://libgen.li/index.php?req={}&res=100".format(
                                quote(isbn)
                            ),
                        )
                        if html2 and html2[0]:
                            mm = re.search(r"ads\.php\?md5=([a-f0-9]{32})", html2[0])
                            if mm:
                                md5 = mm.group(1)
                                break
                if not md5:
                    q = quote(re.split(r"\s*\|\s*", obj.get("name") or "")[0])
                    html2 = await Scraper().get_all_results(
                        session,
                        "https://libgen.li/index.php?req={}&res=100".format(q),
                    )
                    if html2 and html2[0]:
                        mm = re.search(r"ads\.php\?md5=([a-f0-9]{32})", html2[0])
                        md5 = mm.group(1) if mm else None
                if not md5:
                    return None
                html2 = await Scraper().get_all_results(
                    session, "https://libgen.li/ads.php?md5=" + md5
                )
                if not html2 or not html2[0]:
                    return None
                m = re.search(
                    r'href="(get\.php\?md5=[a-f0-9]{32}&key=[A-Z0-9]+)"',
                    html2[0],
                )
                if not m:
                    return None
                obj["torrent"] = "https://libgen.li/" + m.group(1)
                obj["download"] = obj["torrent"]
                obj["md5"] = md5
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
            if solution.get("status") != 200 or "/books/" not in html:
                return []
            return self._parser(html)
        except Exception:
            return []

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(
            connector=get_connector(), connector_owner=False, trust_env=True,
            timeout=timeout,
        ) as session:
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
