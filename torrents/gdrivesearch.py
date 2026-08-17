import asyncio
import os
import re
import time
from html import unescape
from urllib.parse import quote, unquote

import aiohttp

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
_flare_lock = asyncio.Lock()

_DDG_SEARCH = "https://html.duckduckgo.com/html/?q=site%3Adrive.google.com+{query}"
_DRIVE_FILE_RE = re.compile(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]{20,})")
_DRIVE_ANY_RE = re.compile(r"drive\.google\.com/[^\"]*?([a-zA-Z0-9_-]{20,})")


def _drive_direct_link(file_id):
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def _drive_view_link(file_id):
    return f"https://drive.google.com/file/d/{file_id}/view"


async def _flare_ddg_search(query, timeout_sec=30):
    """Search via DuckDuckGo HTML through FlareSolverr (only method that works for Drive dorks)."""
    url = _DDG_SEARCH.format(query=quote(query))
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
        title = unescape(title_raw)
        uddg = re.search(r"uddg=([^&\"]+)", href)
        if not uddg:
            continue
        real_url = unquote(uddg.group(1))
        if "drive.google.com" not in real_url:
            continue

        is_file = bool(_DRIVE_FILE_RE.search(real_url))
        is_folder = "folders/" in real_url

        id_m = _DRIVE_ANY_RE.search(real_url)
        if not id_m:
            continue
        file_id = id_m.group(1)
        if file_id in seen:
            continue
        seen.add(file_id)

        if not title or title == "Google Drive":
            title = f"GDrive: {file_id[:16]}..."
        if is_folder:
            title = f"📁 {title}"

        out.append((file_id, title, is_file))

    # Files first, then folders
    out.sort(key=lambda x: (not x[2], x[1]))
    return [(fid, title) for fid, title, _ in out]


class GDriveSearch:
    _name = "GDrive Search"

    def __init__(self):
        self.BASE_URL = "https://drive.google.com"
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
        for file_id, title in page_slice:
            data.append({
                "name": title,
                "url": _drive_view_link(file_id),
                "torrent": _drive_direct_link(file_id),
                "download": _drive_direct_link(file_id),
                "hash": file_id,
                "category": "GDrive",
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
