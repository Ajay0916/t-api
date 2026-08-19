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
        self.BASE_URL = "https://downloadly.ir"
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

    async def _fetch(self, url, timeout=30, session_id=None):
        # downloadly.ir blocks direct curl from VPS IPs — use FlareSolverr with session
        FLARE = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
        try:
            payload = {"cmd": "request.get", "url": url, "maxTimeout": timeout * 1000}
            if session_id:
                payload["session"] = session_id
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
        # Fallback: retry without session if session request failed
        if session_id:
            try:
                payload2 = {"cmd": "request.get", "url": url, "maxTimeout": timeout * 1000}
                async with aiohttp.ClientSession(
                    connector=get_connector(), connector_owner=False, trust_env=True
                ) as s2:
                    async with s2.post(
                        f"{FLARE}/v1", json=payload2,
                        timeout=aiohttp.ClientTimeout(total=timeout + 5)
                    ) as res2:
                        data2 = await res2.json(content_type=None)
                sol2 = data2.get("solution") or {}
                if sol2.get("status") == 200:
                    html2 = sol2.get("response") or ""
                    if html2 and len(html2) > 500:
                        return html2
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
        async with sem:
            page = await self._fetch(url, timeout=12, session_id=session_id)
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
            # Extract size from first part text
            size_match = re.search(r"([\d.]+\s*(?:GB|MB|KB|TB))", dl_links[0].get("text", ""), re.I)
            if size_match:
                obj["size"] = size_match.group(1)
            if len(dl_links) > 1:
                obj["parts"] = dl_links
                # Convert parts to torrents sub-results format
                # so Vj-wz bot renders each part as a separate download
                torrents = []
                for pl in dl_links:
                    torrents.append({
                        "quality": pl.get("text", ""),
                        "type": "RAR",
                        "size": "",
                        "torrent": pl["url"],
                    })
                obj["torrents"] = torrents
                # Translate Persian part labels to English
                async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as ts:
                    for t in obj["torrents"]:
                        t["quality"] = await _translate_text(ts, t.get("quality", ""))
                        # Extract size from translated text (e.g. "Download Part 1 – 1 GB")
                        size_match = re.search(r"([\d.]+\s*(?:GB|MB|KB|TB))", t["quality"], re.I)
                        if size_match:
                            t["size"] = size_match.group(1)
                        # Register short token for each part
                        if t.get("torrent"):
                            t["short"] = register(t["torrent"], obj.get("name") or "", "rar")
            # Try to get better name from page
            h1 = soup.select_one("h1")
            if h1:
                name = h1.get_text(" ", strip=True)
                if name:
                    obj["name"] = name

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        FLARE = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
        # Create a persistent FlareSolverr session (solve CF once, reuse cookies)
        await self._create_session(FLARE)
        try:
            return await self._search_inner(query, page, limit, start_time)
        finally:
            await self._destroy_session(FLARE)

    async def _search_inner(self, query, page, limit, start_time):
        url = "{}/?s={}".format(self.BASE_URL, quote(query))
        html = await self._fetch(url, timeout=20, session_id="downloadly")
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
        # Skip post page fetching during search (FlareSolverr too slow).
        # Set post URL as torrent/download — parts resolved lazily via
        # the torrent_file endpoint with resolve_downloadly_parts().
        for o in results:
            o["torrent"] = o["url"]
            o["download"] = o["url"]
            o["_downloadly_post"] = True  # flag for lazy resolution
        return {
            "data": results[:limit] if limit else results,
            "current_page": page,
            "total_pages": 1,
            "time": time.time() - start_time,
            "total": len(results),
        }


    @staticmethod
    async def resolve_parts(post_url):
        """Fetch download links from a downloadly post page via FlareSolverr session."""
        import aiohttp as _aiohttp
        from helper.session import get_connector as _gc
        FLARE = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
        sid = "downloadly_resolve"
        # Create session
        try:
            async with _aiohttp.ClientSession(connector=_gc(), connector_owner=False, trust_env=True) as s:
                await s.post(f"{FLARE}/v1", json={"cmd": "sessions.create", "session": sid},
                             timeout=_aiohttp.ClientTimeout(total=10))
                payload = {"cmd": "request.get", "url": post_url, "maxTimeout": 20000, "session": sid}
                async with s.post(f"{FLARE}/v1", json=payload, timeout=_aiohttp.ClientTimeout(total=25)) as res:
                    data = await res.json(content_type=None)
                await s.post(f"{FLARE}/v1", json={"cmd": "sessions.destroy", "session": sid},
                             timeout=_aiohttp.ClientTimeout(total=5))
        except Exception:
            return []
        sol = data.get("solution") or {}
        if sol.get("status") != 200:
            return []
        html = sol.get("response") or ""
        if not html or len(html) < 500:
            return []
        soup = BeautifulSoup(html, "html.parser")
        dl_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "dl.downloadly.ir" not in href:
                continue
            if "/Sample/" in href:
                continue
            text = a.get_text(" ", strip=True)
            dl_links.append({"url": href, "text": text})
        # Translate + register short tokens
        if dl_links:
            async with _aiohttp.ClientSession(connector=_gc(), connector_owner=False, trust_env=True) as ts:
                for dl in dl_links:
                    dl["text"] = await _translate_text(ts, dl["text"])
                    sm = re.search(r"([\d.]+\s*(?:GB|MB|KB|TB))", dl["text"], re.I)
                    dl["size"] = sm.group(1) if sm else ""
                    dl["short"] = register(dl["url"], "", "rar")
        return dl_links

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
