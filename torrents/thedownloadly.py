import asyncio
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup

from constants.base_url import THEDOWNLOADLY
from helper.plain_curl import fetch_plain

# Downloadly mirror - WordPress course posts with direct download links
# (Google Drive folders, Mega, MediaFire, ...). Search page lists the posts,
# each post page is fetched (concurrency-limited) to pull its first usable
# download link as the torrent/direct field.
_HOSTERS = re.compile(
    r"(drive\.google\.com|mega\.nz|mediafire\.com|1fichier\.com|"
    r"katfile\.com|rapidgator\.net|uploadgig\.com|nitroflare\.com|"
    r"megaup\.net|gofile\.io|vikingfile\.com|datanodes\.to|fileq\.net)"
)
_SKIP_SLUGS = (
    "category",
    "tag",
    "page",
    "feed",
    "wp-",
    "privacy",
    "about",
    "contact",
    "terms",
    "login",
    "register",
    "request-for-course",
)


class TheDownloadly:
    _name = "The Downloadly"

    def __init__(self):
        self.BASE_URL = THEDOWNLOADLY
        self.LIMIT = None

    async def _fetch(self, url):
        html = await fetch_plain(url, timeout=10)
        if html:
            return html
        return await fetch_plain(url, timeout=10, family=6)

    async def _course_page(self, url, obj, sem):
        async with sem:
            page = await self._fetch(url)
            if not page:
                return
            soup = BeautifulSoup(page, "html.parser")
            best = None
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not _HOSTERS.search(href):
                    continue
                if best is None or "drive.google.com" in href:
                    best = href
            if not best:
                return
            obj["torrent"] = best
            obj["download"] = best
            h1 = soup.select_one("h1")
            if h1:
                name = h1.get_text(" ", strip=True)
                if name:
                    obj["name"] = name

    async def search(self, query, page, limit):
        start_time = time.time()
        url = "{}/?s={}&paged={}".format(self.BASE_URL, quote(query), max(int(page or 1), 1))
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
        results = []
        seen = set()
        for a in soup.select("h2 a[href], h4 a[href]"):
            href = a["href"]
            if href in seen or not href.startswith(self.BASE_URL + "/"):
                continue
            if any(s in href for s in _SKIP_SLUGS):
                continue
            name = a.get_text(" ", strip=True)
            if not name:
                continue
            seen.add(href)
            results.append({"name": name, "url": href, "category": "Courses"})
            if limit and len(results) >= limit:
                break
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
            *[asyncio.create_task(self._course_page(o["url"], o, sem)) for o in results]
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
