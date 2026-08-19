import asyncio
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup
from helper.plain_curl import fetch_plain
from helper.session import get_connector

import aiohttp
from constants.headers import HEADER_AIO, AIO_TIMEOUT

# downloadly.ir - WordPress site with direct dl.downloadly.ir file links.
# Posts have multi-part downloads (بخش 1, بخش 2, ...).
_SKIP_SLUGS = (
    "category", "tag", "page", "feed", "wp-",
    "privacy", "about", "contact", "terms",
    "advertisement", "donate", "support",
)


class Downloadly:
    _name = "Downloadly"

    def __init__(self):
        self.BASE_URL = "https://downloadly.ir"
        self.LIMIT = None

    async def _fetch(self, url, timeout=20):
        html = await fetch_plain(url, timeout=timeout)
        if html:
            return html
        # Try IPv6
        html = await fetch_plain(url, timeout=timeout, family=6)
        if html:
            return html
        # Last resort: aiohttp with Chrome UA
        try:
            async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as s:
                async with s.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                    if r.status == 200:
                        return await r.text()
        except Exception:
            pass
        return None

    def _parse_search(self, html):
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for item in soup.find_all("div", class_=lambda c: c and "w-grid-item" in c):
            title_el = item.find("a", class_=lambda c: c and "entry-title" in c)
            if not title_el:
                pc = item.find(class_=lambda c: c and "post_title" in c)
                title_el = pc.find("a") if pc else None
            if not title_el or not title_el.has_attr("href"):
                continue
            href = title_el["href"]
            if any(s in href for s in _SKIP_SLUGS):
                continue
            name = title_el.get_text(" ", strip=True)
            if not name:
                continue
            img = item.find("img")
            poster = img["src"] if img and img.has_attr("src") else None
            results.append({
                "name": name,
                "url": href,
                "poster": poster,
                "category": "Courses",
            })
        return results

    async def _post_page(self, url, obj, sem):
        async with sem:
            page = await self._fetch(url)
            if not page:
                return
            soup = BeautifulSoup(page, "html.parser")
            # Extract download links from dl.downloadly.ir
            dl_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "dl.downloadly.ir" not in href:
                    continue
                text = a.get_text(" ", strip=True)
                # Skip sample files
                if "/Sample/" in href:
                    continue
                dl_links.append({"url": href, "text": text})
            if not dl_links:
                return
            # Use first part as torrent/download, collect all parts
            obj["torrent"] = dl_links[0]["url"]
            obj["download"] = dl_links[0]["url"]
            if len(dl_links) > 1:
                obj["parts"] = dl_links
            # Try to get better name from page
            h1 = soup.select_one("h1")
            if h1:
                name = h1.get_text(" ", strip=True)
                if name:
                    obj["name"] = name

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        url = "{}/?s={}".format(self.BASE_URL, quote(query))
        html = await self._fetch(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        if "no results" in (soup.get_text(" ", strip=True) or "").lower():
            return {
                "data": [],
                "current_page": page,
                "total_pages": 1,
                "time": time.time() - start_time,
                "total": 0,
            }
        results = self._parse_search(html)
        if not results:
            return {
                "data": [],
                "current_page": page,
                "total_pages": 1,
                "time": time.time() - start_time,
                "total": 0,
            }
        sem = asyncio.Semaphore(6)
        await asyncio.gather(
            *[asyncio.create_task(self._post_page(o["url"], o, sem)) for o in results]
        )
        results = [o for o in results if o.get("torrent")]
        return {
            "data": results[:limit] if limit else results,
            "current_page": page,
            "total_pages": 1,
            "time": time.time() - start_time,
            "total": len(results),
        }

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
