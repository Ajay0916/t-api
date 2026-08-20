import os
"""downloadly.ir — WordPress course site with dl.downloadly.ir direct links.

Search page lists posts; each post page is fetched (concurrency-limited)
to extract all download links. The first link becomes torrent/download;
if multiple parts exist, they're stored in 'torrents' sub-results so
Vj-wz renders each as a separate download button.
"""
import asyncio
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup

from constants.base_url import DOWNLOADLY
from helper.plain_curl import fetch_plain
from helper.session import get_connector
from helper.short_links import register

import aiohttp

_TRANS_URL = "https://api.mymemory.translated.net/get"
_TRANS_CACHE = {}
_PERSIAN_RE = re.compile(r"[\u0600-\u06FF]")


def _is_persian(text):
    return bool(_PERSIAN_RE.search(text or ""))


async def _translate_text(session, text, src="fa", dst="en"):
    if not text or not _is_persian(text):
        return text
    if text in _TRANS_CACHE:
        return _TRANS_CACHE[text]
    try:
        url = "{0}?q={1}&langpair={2}|{3}".format(
            _TRANS_URL, quote(text[:480]), src, dst
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as res:
            data = await res.json(content_type=None)
        out = ((data or {}).get("responseData") or {}).get("translatedText") or ""
        out = str(out).strip()
        if out and out.lower() != text.lower() and "QUERY LENGTH" not in out.upper():
            _TRANS_CACHE[text] = out
            return out
    except Exception:
        pass
    _TRANS_CACHE[text] = text
    return text


_SKIP_SLUGS = (
    "category", "tag", "page", "feed", "wp-",
    "privacy", "about", "contact", "terms",
    "advertisement", "donate", "support",
)


class Downloadly:
    _name = "Downloadly"

    def __init__(self):
        self.BASE_URL = DOWNLOADLY
        self.LIMIT = None

    async def _fetch(self, url, timeout=12):
        """FlareSolverr for search pages (proven to work)."""
        FLARE = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
        try:
            payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout * 1000}
            async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as s:
                async with s.post(f"{FLARE}/v1", json=payload, timeout=aiohttp.ClientTimeout(total=timeout + 10)) as res:
                    data = await res.json(content_type=None)
            sol = data.get("solution") or {}
            if sol.get("status") == 200:
                html = sol.get("response") or ""
                if html and len(html) > 500:
                    return html
        except Exception:
            pass
        return None

    async def _post_page(self, url, obj, sem):
        async with sem:
            page = await self._fetch(url)
            if not page or len(page) < 500:
                return
            soup = BeautifulSoup(page, "html.parser")
            dl_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not re.match(r"https?://dl\d*\.downloadly\.ir/", href):
                    continue
                if "/Sample/" in href or href.lower().endswith((".mp4", ".mp3")):
                    continue
                text = a.get_text(" ", strip=True)
                dl_links.append({"url": href, "text": text})
            if not dl_links:
                return
            obj["torrent"] = dl_links[0]["url"]
            obj["download"] = dl_links[0]["url"]
            sm = re.search(
                r"([\d.]+\s*(?:GB|MB|KB|TB))",
                dl_links[0].get("text", ""), re.I,
            )
            if sm:
                obj["size"] = sm.group(1)
            if len(dl_links) > 1:
                obj["parts"] = dl_links
                torrents = []
                for pl in dl_links:
                    torrents.append({
                        "quality": pl.get("text", ""),
                        "type": "RAR",
                        "size": "",
                        "torrent": pl["url"],
                    })
                obj["torrents"] = torrents
                async with aiohttp.ClientSession(
                    connector=get_connector(), connector_owner=False, trust_env=True
                ) as ts:
                    for t in obj["torrents"]:
                        t["quality"] = await _translate_text(ts, t.get("quality", ""))
                        sm = re.search(
                            r"([\d.]+\s*(?:GB|MB|KB|TB))",
                            t["quality"], re.I,
                        )
                        if sm:
                            t["size"] = sm.group(1)
                        if t.get("torrent"):
                            t["short"] = register(
                                t["torrent"], obj.get("name") or "", "rar"
                            )
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
            return {
                "data": [],
                "current_page": page,
                "total_pages": 1,
                "time": time.time() - start_time,
                "total": 0,
            }
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
            results.append({
                "name": name,
                "url": href,
                "category": "Courses",
            })
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
        sem = asyncio.Semaphore(3)
        await asyncio.gather(
            *[asyncio.create_task(self._post_page(o["url"], o, sem))
              for o in results]
        )
        # Fallback: set post URL as torrent if _post_page didn't find dl links
        for o in results:
            if not o.get("torrent"):
                o["torrent"] = o["url"]
                o["download"] = o["url"]
                o["_downloadly_post"] = True
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
