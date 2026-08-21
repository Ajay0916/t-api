"""downloadly.ir — WordPress course site with dl*.downloadly.ir direct links.
Fresh implementation using fetch_plain (system curl), no proxy/mirror."""
import asyncio
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup

import os
import aiohttp

from constants.base_url import DOWNLOADLY
from helper.plain_curl import fetch_plain

_MIRROR_URL = "https://downloadlynet.ir"
_FLARE_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")

_SKIP_SLUGS = (
    "category", "tag", "page", "feed", "wp-",
    "privacy", "about", "contact", "terms",
)

_DL_RE = re.compile(r"https?://dl\d*\.downloadly\.ir/")
_PART_RE = re.compile(r"([\d.]+)\s*(?:گیگابایت|GB)", re.I)


def _parse_parts(html):
    """Extract download links + Persian labels from a post page."""
    soup = BeautifulSoup(html, "html.parser")
    parts = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _DL_RE.match(href) or "/Sample/" in href or href in seen:
            continue
        seen.add(href)
        text = a.get_text(" ", strip=True)
        size_m = _PART_RE.search(text)
        size = f"{size_m.group(1)} GB" if size_m else ""
        # Convert Persian part label to English
        part_num = re.search(r"بخش\s*(\d+)", text)
        label = f"Part {part_num.group(1)}" if part_num else text[:40]
        if size:
            label += f" — {size}"
        parts.append({"url": href, "label": label, "size": size})
    return parts


class Downloadly:
    _name = "Downloadly"

    def __init__(self):
        self.BASE_URL = DOWNLOADLY
        self.LIMIT = None

    async def _fetch(self, url, timeout=15):
        # 1. Plain curl on primary domain
        html = await fetch_plain(url, timeout=timeout)
        if html and len(html) > 500:
            return html
        # 2. Plain curl on mirror domain
        mirror = url.replace("downloadly.ir", "downloadlynet.ir", 1)
        html = await fetch_plain(mirror, timeout=timeout)
        if html and len(html) > 500:
            return html
        # 3. FlareSolverr fallback
        return await self._fetch_flare(url, timeout)

    async def _fetch_flare(self, url, timeout=15):
        try:
            payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout * 1000}
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{_FLARE_URL}/v1", json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout + 10),
                ) as res:
                    data = await res.json(content_type=None)
            sol = data.get("solution") or {}
            if sol.get("status") == 200:
                html = sol.get("response") or ""
                if len(html) > 500:
                    return html
        except Exception:
            pass
        return None

    async def _post_page(self, url, obj, sem):
        async with sem:
            page = await self._fetch(url)
            if not page:
                return
            parts = _parse_parts(page)
            if not parts:
                return
            obj["torrent"] = parts[0]["url"]
            obj["download"] = parts[0]["url"]
            h1 = BeautifulSoup(page, "html.parser").select_one("h1")
            if h1:
                name = h1.get_text(" ", strip=True)
                if name:
                    obj["name"] = name
            if len(parts) > 1:
                obj["torrents"] = [
                    {
                        "quality": p["label"],
                        "type": "RAR",
                        "size": p["size"],
                        "torrent": p["url"],
                    }
                    for p in parts
                ]

    async def search(self, query, page, limit):
        start_time = time.time()
        url = "{}/?s={}".format(self.BASE_URL, quote(query))
        html = await self._fetch(url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        results = []
        seen = set()
        for div in soup.find_all("div", class_=lambda c: c and "w-grid-item" in c):
            h2 = div.find("h2", class_=lambda c: c and "entry-title" in c)
            a = h2.find("a", href=True) if h2 else None
            if not a:
                continue
            href = a["href"]
            if href in seen or any(s in href for s in _SKIP_SLUGS):
                continue
            name = a.get_text(" ", strip=True)
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
            *[asyncio.create_task(self._post_page(o["url"], o, sem)) for o in results]
        )
        results = [o for o in results if o.get("torrent")]
        return {"data": results[:limit] if limit else results,
                "current_page": page, "total_pages": 1,
                "time": time.time() - start_time, "total": len(results)}

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
