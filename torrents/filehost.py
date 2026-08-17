import asyncio
import os
import re
import time
from urllib.parse import quote, unquote

import aiohttp

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
_flare_lock = asyncio.Lock()

_CATBOX_RE = re.compile(r"files\.catbox\.moe/([a-zA-Z0-9]+\.[a-z0-9]+)")
_JUNK = re.compile(
    r"security.check|not.a.robot|captcha|cloudflare|please.wait|boba.bot",
    re.I,
)


def _extract_results(html):
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

        id_m = _CATBOX_RE.search(real_url)
        if not id_m:
            continue
        filename = id_m.group(1)
        if filename in seen:
            continue
        seen.add(filename)

        # Clean title
        name = unquote(title_raw).strip()
        name = re.sub(r"\s*[-–|]?\s*files?\.catbox\.moe\s*$", "", name, flags=re.I).strip()
        name = re.sub(r"^(PDF|ZIP|RAR|MP4|MP3|EXE|7Z|ISO|EPUB|TXT)\s+", "", name, flags=re.I).strip()

        # If title is junk or too short, use filename
        if not name or len(name) < 3 or _JUNK.search(name) or name.lower() in ("catbox", "catbox tools"):
            name = filename

        out.append({
            "name": name,
            "url": real_url,
            "hash": filename,
            "platform": "CATBOX",
        })

    return out


async def _flare_ddg_search(query, timeout_sec=30):
    dork = "site:files.catbox.moe"
    url = f"https://html.duckduckgo.com/html/?q={quote(dork + ' ' + query)}"
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": timeout_sec * 1000,
        "session": "filehost",
    }
    try:
        async with _flare_lock:
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=10, force_close=True, ssl=False),
                connector_owner=True, trust_env=True,
            ) as session:
                async with session.post(
                    f"{FLARESOLVERR_URL}/v1", json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout_sec + 15),
                ) as res:
                    data = await res.json(content_type=None)
        solution = data.get("solution") or {}
        if solution.get("status") != 200:
            return []
        html = solution.get("response") or ""
    except Exception:
        return []
    return _extract_results(html)


class FileHostSearch:
    _name = "FileHost"

    def __init__(self):
        self.BASE_URL = ""
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
        for item in page_slice:
            data.append({
                "name": item["name"],
                "url": item["url"],
                "torrent": item["url"],
                "download": item["url"],
                "hash": item["hash"],
                "category": "CATBOX",
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
