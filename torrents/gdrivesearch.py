import asyncio
import os
import re
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
_flare_lock = asyncio.Lock()

# Google Dorking: search for public Google Drive files/folders
_GOOGLE_SEARCH = "https://www.google.com/search?q={query}&num={num}&start={start}"
_DRIVE_PATTERN = re.compile(
    r'(?:(?:drive\.google\.com/(?:file/d|open\?id|folderview\?id)=|'
    r'docs\.google\.com/(?:uc\?id|open\?id)=))([a-zA-Z0-9_-]{20,})'
)
_TITLE_PATTERN = re.compile(r'<h3[^>]*>(.*?)</h3>', re.S)
# Broader: also catch /d/<id>/ and /d/<id>/view patterns
_DRIVE_BROAD = re.compile(r'drive\.google\.com/[^"\']*/([a-zA-Z0-9_-]{20,})')


def _clean_title(raw):
    text = re.sub(r'<[^>]+>', '', raw)
    text = text.replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"')
    return text.strip()


def _drive_direct_link(file_id):
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def _drive_view_link(file_id):
    return f"https://drive.google.com/file/d/{file_id}/view"


def _extract_ids_and_titles(html):
    """Extract Drive file IDs and surrounding titles from Google HTML."""
    results = []
    seen = set()

    for match in _DRIVE_PATTERN.finditer(html):
        file_id = match.group(1)
        if file_id in seen:
            continue
        seen.add(file_id)
        pos = match.start()
        chunk = html[max(0, pos - 800):pos + 300]
        title_match = _TITLE_PATTERN.search(chunk)
        title = _clean_title(title_match.group(1)) if title_match else f"GDrive: {file_id[:16]}..."
        results.append((file_id, title))

    # Also catch broader patterns if main regex missed some
    if not results:
        for match in _DRIVE_BROAD.finditer(html):
            fid = match.group(1)
            if fid not in seen and len(fid) >= 20:
                seen.add(fid)
                pos = match.start()
                chunk = html[max(0, pos - 800):pos + 300]
                title_match = _TITLE_PATTERN.search(chunk)
                title = _clean_title(title_match.group(1)) if title_match else f"GDrive: {fid[:16]}..."
                results.append((fid, title))

    return results


class GDriveSearch:
    _name = "GDrive Search"

    def __init__(self):
        self.BASE_URL = "https://drive.google.com"
        self.LIMIT = None

    async def _flaresolverr_get(self, url, timeout_sec=25):
        """Fetch a URL through FlareSolverr (handles JS/Cloudflare)."""
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": timeout_sec * 1000,
            "session": "gdrive",
        }
        try:
            async with _flare_lock:
                async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(limit=10, force_close=True, ssl=False),
                    connector_owner=True, trust_env=True,
                ) as session:
                    async with session.post(
                        f"{FLARESOLVERR_URL}/v1",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=timeout_sec + 15),
                    ) as res:
                        data = await res.json(content_type=None)
            solution = data.get("solution") or {}
            if solution.get("status") != 200:
                return None
            return solution.get("response") or ""
        except Exception:
            return None

    async def search(self, query, page, limit):
        start_time = time.time()
        per = limit or 10
        page_num = max(int(page or 1), 1)
        start = (page_num - 1) * per

        dork = f'site:drive.google.com "{query}"'
        url = _GOOGLE_SEARCH.format(
            query=quote(dork),
            num=min(per + 5, 20),
            start=start,
        )

        html = await self._flaresolverr_get(url, timeout_sec=30)
        if not html:
            return None

        ids_titles = _extract_ids_and_titles(html)
        results = []
        for file_id, title in ids_titles[:limit]:
            results.append({
                "name": title,
                "url": _drive_view_link(file_id),
                "torrent": _drive_direct_link(file_id),
                "download": _drive_direct_link(file_id),
                "hash": file_id,
                "category": "GDrive",
                "size": "",
            })

        total_pages = max(1, page_num + 1) if len(results) >= per else page_num

        return {
            "data": results,
            "current_page": page_num,
            "total_pages": total_pages,
            "time": time.time() - start_time,
            "total": len(results),
        }

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
