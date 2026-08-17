import asyncio
import os
import re
import time
from urllib.parse import quote, unquote, urlparse

import aiohttp

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
_flare_lock = asyncio.Lock()

_DDG_SEARCH = "https://html.duckduckgo.com/html/?q=site%3Amediafire.com+{query}"
_MF_FILE_RE = re.compile(r"mediafire\.com/file/([a-zA-Z0-9]+)/([^/]+?)(?:/file)?(?:\?|$)")


def _clean_filename(raw):
    """Decode URL-encoded filename and clean up."""
    name = unquote(raw).replace("+", " ").strip()
    name = re.sub(r"\.(file|html)$", "", name, flags=re.I)
    return name


def _extract_from_url(url):
    """Extract file_id and filename from MediaFire URL."""
    m = _MF_FILE_RE.search(url)
    if m:
        return m.group(1), _clean_filename(m.group(2))
    return None, None


def _download_link(file_id):
    return f"https://www.mediafire.com/file/{file_id}/file"


async def _flare_ddg_search(query, timeout_sec=30):
    """Search via DuckDuckGo HTML through FlareSolverr."""
    url = _DDG_SEARCH.format(query=quote(query))
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": timeout_sec * 1000,
        "session": "mediafire",
    }
    try:
        async with _flare_lock:
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=10, force_close=True, ssl=False),
                connector_owner=True,
                trust_env=True,
            ) as session:
                async with session.post(
                    f"{FLARESOLVERR_URL}/v1",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout_sec + 15),
                ) as res:
                    data = await res.json(content_type=None)
        solution = data.get("solution") or {}
        if solution.get("status") != 200:
            return []
        html = solution.get("response") or ""
    except Exception:
        return []

    seen = set()
    out = []
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S
    ):
        href = m.group(1)
        title_raw = re.sub(r"<[^>]+>", "", m.group(2)).strip()

        uddg = re.search(r"uddg=([^&\"]+)", href)
        if not uddg:
            continue
        real_url = unquote(uddg.group(1))

        if "mediafire.com/file/" not in real_url:
            continue

        file_id, filename = _extract_from_url(real_url)
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)

        # Use filename from URL (best source), fallback to title
        name = filename if filename and filename != "file" else unquote(title_raw)
        if not name or name in ("MediaFire", "File sharing and storage made simple"):
            name = f"MediaFire: {file_id[:16]}..."

        out.append((file_id, name, real_url))

    return out


class MediaFireSearch:
    _name = "MediaFire"

    def __init__(self):
        self.BASE_URL = "https://www.mediafire.com"
        self.LIMIT = None

    async def search(self, query, page, limit):
        start_time = time.time()
        per = limit or 10
        page_num = max(int(page or 1), 1)

        results = await _flare_ddg_search(query)

        if not results:
            return None

        start_idx = (page_num - 1) * per
        page_slice = results[start_idx : start_idx + per]

        data = []
        for file_id, name, url in page_slice:
            data.append({
                "name": name,
                "url": url,
                "torrent": url,
                "download": url,
                "hash": file_id,
                "category": "MediaFire",
                "size": "",
            })

        has_more = len(results) > start_idx + per
        total_pages = page_num + 1 if has_more else page_num

        return {
            "data": data,
            "current_page": page_num,
            "total_pages": max(1, total_pages),
            "time": time.time() - start_time,
            "total": len(data),
        }

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
