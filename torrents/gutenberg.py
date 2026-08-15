import asyncio
import re
import time
from datetime import datetime
from urllib.parse import quote

from bs4 import BeautifulSoup

from constants.base_url import GUTENBERG
from helper.plain_curl import fetch_plain

# Project Gutenberg: free public-domain ebooks. Search returns the book
# cards; every book page is fetched (concurrency-limited) to pick the best
# downloadable format (EPUB -> Kindle -> plain text) as the direct link.
_FORMAT_RE = re.compile(r'href="(/ebooks/\d+\.(?:epub[^"]*|kindle[^"]*|txt[^"]*))"')


def _pick_format(page):
    links = {}
    for m in _FORMAT_RE.finditer(page):
        href = m.group(1)
        if ".epub" in href:
            links.setdefault("epub", href)
        elif ".kindle" in href:
            links.setdefault("kindle", href)
        else:
            links.setdefault("txt", href)
    for key in ("epub", "kindle", "txt"):
        if key in links:
            return links[key]
    return None


class Gutenberg:
    _name = "Project Gutenberg"

    def __init__(self):
        self.BASE_URL = GUTENBERG
        self.LIMIT = None

    async def _fetch(self, url):
        html = await fetch_plain(url, timeout=10)
        if html:
            return html
        return await fetch_plain(url, timeout=10, family=6)

    async def _book_page(self, url, obj, sem):
        async with sem:
            page = await self._fetch(url)
            if not page:
                return
            href = _pick_format(page)
            if not href:
                return
            obj["torrent"] = self.BASE_URL + href
            obj["download"] = obj["torrent"]
            soup = BeautifulSoup(page, "html.parser")
            h1 = soup.select_one("h1")
            if h1:
                obj["name"] = h1.get_text(" ", strip=True)
            m = re.search(r'itemprop="datePublished">([^<]+)', page)
            if m:
                try:
                    obj["date"] = datetime.strptime(
                        m.group(1).strip(), "%b %d, %Y"
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    obj["date"] = m.group(1).strip()

    async def search(self, query, page, limit):
        start_time = time.time()
        url = "{}/ebooks/search/?query={}".format(self.BASE_URL, quote(query))
        html = await self._fetch(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for li in soup.select("li.booklink"):
            a = li.select_one("a[href]")
            if not a or not re.search(r"/ebooks/\d+$", a.get("href", "")):
                continue
            name = a.get_text(" ", strip=True)
            if not name:
                continue
            author = ""
            sub = li.select_one("span.subtitle")
            if sub:
                author = sub.get_text(" ", strip=True)
            results.append(
                {
                    "name": name,
                    "author": author,
                    "url": self.BASE_URL + a["href"],
                    "category": "Books",
                    "size": "",
                }
            )
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
            *[asyncio.create_task(self._book_page(o["url"], o, sem)) for o in results]
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
