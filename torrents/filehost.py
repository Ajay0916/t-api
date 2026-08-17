import asyncio
import os
import re
import time
from urllib.parse import quote, unquote

import aiohttp

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
_flare_lock = asyncio.Lock()

# ── Platform definitions ────────────────────────────────────────────
PLATFORMS = {
    "mega": {
        "dork": "site:mega.nz/file OR site:mega.co.nz/file",
        "url_re": re.compile(r"(?:mega\.nz|mega\.co\.nz)/file/([a-zA-Z0-9]+#[a-zA-Z0-9]+)"),
        "name_re": re.compile(r"mega\.(?:nz|co\.nz)/file/([a-zA-Z0-9]+)(?:#([^/]+))?"),
        "view": "https://mega.nz/file/{id}",
    },
    "workupload": {
        "dork": "site:workupload.com/file",
        "url_re": re.compile(r"workupload\.com/file/([a-zA-Z0-9]+)"),
        "view": "https://workupload.com/file/{id}",
    },
    "gofile": {
        "dork": "site:gofile.io/d",
        "url_re": re.compile(r"gofile\.io/d/([a-zA-Z0-9]+)"),
        "view": "https://gofile.io/d/{id}",
    },
    "catbox": {
        "dork": "site:catbox.moe OR site:files.catbox.moe",
        "url_re": re.compile(r"(?:files\.)?catbox\.moe/([a-zA-Z0-9]+\.[a-z0-9]+)"),
        "view": "https://files.catbox.moe/{id}",
    },
    "1fichier": {
        "dork": "site:1fichier.com",
        "url_re": re.compile(r"1fichier\.com/([a-zA-Z0-9]+)"),
        "view": "https://1fichier.com/{id}",
    },
    "bayfiles": {
        "dork": "site:bayfiles.com/file",
        "url_re": re.compile(r"bayfiles\.com/file/([a-zA-Z0-9]+)"),
        "view": "https://bayfiles.com/file/{id}",
    },
}


def _build_dork(platforms=None):
    """Build a combined DDG dork for multiple platforms."""
    targets = platforms or list(PLATFORMS.keys())
    parts = []
    for p in targets:
        info = PLATFORMS.get(p)
        if info:
            parts.append(info["dork"])
    return " OR ".join(parts)


def _extract_results(html):
    """Extract file links from DDG HTML results across all platforms."""
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

        # Match against all platforms
        for plat_name, plat_info in PLATFORMS.items():
            id_m = plat_info["url_re"].search(real_url)
            if not id_m:
                continue
            file_id = id_m.group(1)
            dedup_key = f"{plat_name}:{file_id}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Get view URL
            view_url = plat_info["view"].format(id=file_id)

            # Filename: from URL path or title
            name = unquote(title_raw) if title_raw and title_raw not in ("MediaFire", "") else f"{plat_name}: {file_id[:16]}..."

            out.append({
                "name": name,
                "url": view_url,
                "hash": file_id,
                "platform": plat_name.upper(),
            })
            break  # First match wins

    return out


async def _flare_ddg_search(query, timeout_sec=30, platforms=None):
    """Search via DuckDuckGo HTML through FlareSolverr."""
    dork = _build_dork(platforms)
    full_query = f"({dork}) {query}"
    url = f"https://html.duckduckgo.com/html/?q={quote(full_query)}"
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
                "name": f"[{item['platform']}] {item['name']}",
                "url": item["url"],
                "torrent": item["url"],
                "download": item["url"],
                "hash": item["hash"],
                "category": item["platform"],
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
