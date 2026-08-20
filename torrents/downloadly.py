"""downloadly.ir — WordPress course site with dl.downloadly.ir direct links.
Uses wg1 SOCKS5 proxy (ProtonVPN Japan) for VPS IP bypass."""
import asyncio
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup
from aiohttp_socks import ProxyConnector

_SKIP_SLUGS = (
    "category", "tag", "page", "feed", "wp-",
    "privacy", "about", "contact", "terms",
    "advertisement", "donate", "support",
)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_SOCKS_URL = "socks5://127.0.0.1:1080"


async def _fetch_via_socks(url, timeout=20):
    """Fetch URL through SOCKS5 proxy (wg1 VPN)."""
    import logging
    _log = logging.getLogger("downloadly")
    connector = ProxyConnector.from_url(_SOCKS_URL)
    try:
        import aiohttp as _aio
        async with _aio.ClientSession(
            connector=connector,
            headers={"User-Agent": CHROME_UA},
        ) as session:
            _log.info("Fetching %s via SOCKS...", url[:60])
            async with session.get(url, timeout=_aio.ClientTimeout(total=timeout)) as resp:
                _log.info("Status: %d", resp.status)
                if resp.status != 200:
                    return None
                html = await resp.text(errors="replace")
                _log.info("HTML len: %d", len(html))
                if len(html) < 500:
                    return None
                return html
    except Exception as e:
        _log.error("Fetch error: %s", e)
        return None
    finally:
        await connector.close()


class Downloadly:
    _name = "Downloadly"

    def __init__(self):
        self.BASE_URL = "https://downloadly.ir"
        self.LIMIT = None

    async def _fetch(self, url, timeout=20):
        return await _fetch_via_socks(url, timeout)

    async def _post_page(self, url, obj, sem):
        async with sem:
            page = await self._fetch(url)
            if not page:
                return
            soup = BeautifulSoup(page, "html.parser")
            dl_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "dl.downloadly.ir" not in href:
                    continue
                if "/Sample/" in href:
                    continue
                text = a.get_text(" ", strip=True)
                dl_links.append({"url": href, "text": text})
            if not dl_links:
                return
            obj["torrent"] = dl_links[0]["url"]
            obj["download"] = dl_links[0]["url"]
            if len(dl_links) > 1:
                obj["parts"] = dl_links
            h1 = soup.select_one("h1")
            if h1:
                name = h1.get_text(" ", strip=True)
                if name:
                    obj["name"] = name

    async def resolve_parts(self, post_url):
        """Fetch download links from a downloadly post page via SOCKS5 proxy."""
        html = await _fetch_via_socks(post_url, 15)
        if not html or len(html) < 500:
            return []
        soup = BeautifulSoup(html, "html.parser")
        dl_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "dl.downloadly.ir" not in href:
                continue
            if "/Sample/" in href or href.lower().endswith((".mp4", ".mp3")):
                continue
            text = a.get_text(" ", strip=True)
            dl_links.append({"url": href, "text": text})
        seen = set()
        unique = []
        for dl in dl_links:
            if dl["url"] not in seen:
                seen.add(dl["url"])
                unique.append(dl)
        return unique

    async def search(self, query, page, limit):
        start_time = time.time()
        url = "{}/?s={}".format(self.BASE_URL, quote(query))
        html = await self._fetch(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        if "no results" in (soup.get_text(" ", strip=True) or "").lower():
            return {"data": [], "current_page": page, "total_pages": 1,
                    "time": time.time() - start_time, "total": 0}
        results = []
        seen = set()
        for div in soup.find_all("div", class_=lambda c: c and "w-grid-item" in c):
            h2 = div.find("h2", class_=lambda c: c and "entry-title" in c)
            title_el = h2.find("a", href=True) if h2 else None
            if not title_el:
                title_el = div.find("a", class_=lambda c: c and "entry-title" in c)
            if not title_el:
                pc = div.find(class_=lambda c: c and "post_title" in c)
                title_el = pc.find("a") if pc else None
            if not title_el or not title_el.has_attr("href"):
                continue
            href = title_el["href"]
            if href in seen or any(s in href for s in _SKIP_SLUGS):
                continue
            name = title_el.get_text(" ", strip=True)
            if not name:
                continue
            seen.add(href)
            results.append({"name": name, "url": href, "category": "Courses"})
            if limit and len(results) >= limit:
                break
        if not results:
            return {"data": [], "current_page": page, "total_pages": 1,
                    "time": time.time() - start_time, "total": 0}
        sem = asyncio.Semaphore(3)
        await asyncio.gather(
            *[asyncio.create_task(self._post_page(o["url"], o, sem))
              for o in results]
        )
        results = [o for o in results if o.get("torrent")]
        return {"data": results[:limit] if limit else results,
                "current_page": page, "total_pages": 1,
                "time": time.time() - start_time, "total": len(results)}

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
