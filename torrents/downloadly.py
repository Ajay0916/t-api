"""downloadly.ir — WordPress course site with dl.downloadly.ir direct links.
Uses ProtonVPN (wg1) via iptables routing for VPS IP bypass."""
import asyncio
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup

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
        """Fetch via curl --interface wg1 (ProtonVPN Japan)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-sL", "-4", "--interface", "wg1",
                "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0",
                "--max-time", str(timeout), "--", url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
            if out and proc.returncode == 0:
                html = out.decode("utf-8", errors="replace")
                if html and len(html) > 500:
                    return html
        except Exception:
            pass
        return None

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
