import os
import asyncio
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup
from helper.plain_curl import fetch_plain
from helper.session import get_connector
from helper.short_links import register

import aiohttp
from constants.headers import HEADER_AIO, AIO_TIMEOUT

_TRANS_URL = "https://api.mymemory.translated.net/get"
_TRANS_CACHE = {}
_PERSIAN_RE = re.compile(r"[؀-ۿ]")


def _is_persian(text):
    return bool(_PERSIAN_RE.search(text or ""))


async def _translate_text(session, text, src="fa", dst="en"):
    """Translate text via MyMemory free API. Returns original on failure."""
    if not text or not _is_persian(text):
        return text
    if text in _TRANS_CACHE:
        return _TRANS_CACHE[text]
    try:
        url = "{0}?q={1}&langpair={2}|{3}".format(_TRANS_URL, quote(text[:480]), src, dst)
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
        self.BASE_URL = "https://downloadlynet.ir"
        self.LIMIT = None

    async def _create_session(self, flare_url):
        """Create a persistent FlareSolverr session for this search.
        Destroy any stale session first, then create fresh."""
        try:
            async with aiohttp.ClientSession(
                connector=get_connector(), connector_owner=False, trust_env=True
            ) as s:
                # Destroy any leftover session
                try:
                    await s.post(
                        f"{flare_url}/v1",
                        json={"cmd": "sessions.destroy", "session": "downloadly"},
                        timeout=aiohttp.ClientTimeout(total=5)
                    )
                except Exception:
                    pass
                # Create fresh session
                await s.post(
                    f"{flare_url}/v1",
                    json={"cmd": "sessions.create", "session": "downloadly"},
                    timeout=aiohttp.ClientTimeout(total=10)
                )
        except Exception:
            pass

    async def _destroy_session(self, flare_url):
        """Destroy the FlareSolverr session after search."""
        try:
            payload = {"cmd": "sessions.destroy", "session": "downloadly"}
            async with aiohttp.ClientSession(
                connector=get_connector(), connector_owner=False, trust_env=True
            ) as s:
                async with s.post(
                    f"{flare_url}/v1", json=payload,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as res:
                    await res.json(content_type=None)
        except Exception:
            pass

    async def _fetch(self, url, timeout=25):
        # downloadly.ir blocks direct curl from VPS IPs — use FlareSolverr
        FLARE = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
        try:
            payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout * 1000}
            async with aiohttp.ClientSession(
                connector=get_connector(), connector_owner=False, trust_env=True
            ) as s:
                async with s.post(
                    f"{FLARE}/v1", json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout + 5)
                ) as res:
                    data = await res.json(content_type=None)
            sol = data.get("solution") or {}
            if sol.get("status") == 200:
                html = sol.get("response") or ""
                if html and len(html) > 500:
                    return html
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

    async def _post_page(self, url, obj, sem, session_id=None):
        """Fetch post page and extract download links using aiohttp."""
        async with sem:
            page = None
            # Try FlareSolverr first
            try:
                page = await self._fetch(url, timeout=12)
            except Exception:
                pass
            # Fallback: direct aiohttp fetch
            if not page or len(page) < 500:
                try:
                    async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as cs:
                        async with cs.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status == 200:
                                page = await resp.text(content_type=None)
                except Exception:
                    pass
            if not page or len(page) < 500:
                return
            soup = BeautifulSoup(page, "html.parser")
            dl_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not re.match(r"https?://dl\d*\.downloadly\.ir/", href):
                    continue
                if "/Sample/" in href:
                    continue
                text = a.get_text(" ", strip=True)
                dl_links.append({"url": href, "text": text})
            if not dl_links:
                return
            obj["torrent"] = dl_links[0]["url"]
            obj["download"] = dl_links[0]["url"]
            size_match = re.search(r"([\d.]+\s*(?:GB|MB|KB|TB))", dl_links[0].get("text", ""), re.I)
            if size_match:
                obj["size"] = size_match.group(1)
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
                async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as ts:
                    for t in obj["torrents"]:
                        t["quality"] = await _translate_text(ts, t.get("quality", ""))
                        size_match = re.search(r"([\d.]+\s*(?:GB|MB|KB|TB))", t["quality"], re.I)
                        if size_match:
                            t["size"] = size_match.group(1)
                        if t.get("torrent"):
                            t["short"] = register(t["torrent"], obj.get("name") or "", "rar")
            h1 = soup.select_one("h1")
            if h1:
                name = h1.get_text(" ", strip=True)
                if name:
                    obj["name"] = name

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        return await self._search_inner(query, page, limit, start_time)

    async def _search_inner(self, query, page, limit, start_time):
        url = "{}/?s={}".format(self.BASE_URL, quote(query))
        html = await self._fetch(url, timeout=25)
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
        # Set post URL as torrent/download — parts resolved lazily
        for o in results:
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


    async def resolve_parts(self, post_url):
        """Fetch download links via FlareSolverr (only method that works for downloadly)."""
        import logging as _rl
        _log = _rl.getLogger("tapi.downloadly")
        _log.info("resolve_parts: fetching %s", post_url[:80])

        FLARE = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
        html = None
        try:
            payload = {"cmd": "request.get", "url": post_url, "maxTimeout": 35000}
            async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as s:
                async with s.post(
                    f"{FLARE}/v1", json=payload,
                    timeout=aiohttp.ClientTimeout(total=40)
                ) as res:
                    data = await res.json(content_type=None)
            sol = data.get("solution") or {}
            html = sol.get("response")
            _log.info("resolve_parts: flare status=%s html=%d message=%s", 
                sol.get("status"), len(html) if html else 0, 
                (data.get("message") or "")[:80])
        except Exception as e:
            _log.warning("resolve_parts: flare error: %s", str(e)[:80])

        if not html or len(html) < 500:
            return []
        soup = BeautifulSoup(html, "html.parser")
        dl_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not re.match(r"https?://dl\d*\.downloadly\.ir/", href):
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
        dl_links = unique
        _log.info("resolve_parts: found %d links", len(dl_links))
        if dl_links:
            async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as ts:
                for dl in dl_links:
                    dl["text"] = await _translate_text(ts, dl["text"])
                    sm = re.search(r"([\\d.]+\\s*(?:GB|MB|KB|TB))", dl["text"], re.I)
                    dl["size"] = sm.group(1) if sm else ""
                    dl["short"] = register(dl["url"], "", "rar")
        return dl_links

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
