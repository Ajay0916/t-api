import asyncio
import os
import re
import time
from urllib.parse import quote, unquote

import aiohttp

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
_flare_lock = asyncio.Lock()

PLATFORMS = {
    "mega": {
        "dork": "site:mega.nz/file",
        "url_re": re.compile(r"(?:mega\.nz|mega\.co\.nz)/file/([a-zA-Z0-9]+)(?:#([^/\s\"&]+))?"),
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
        "dork": "site:files.catbox.moe",
        "url_re": re.compile(r"files\.catbox\.moe/([a-zA-Z0-9]+\.[a-z0-9]+)"),
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

_JUNK = re.compile(
    r"security.check|not.a.robot|methods.of.identification|captcha"
    r"|attention.required|cloudflare|please.wait|human.verification"
    r"|are.you.a.human|boba.bot|content.*\{\{|use.with",
    re.I,
)


def _extract_results(html, platform_name):
    """Extract file links from DDG HTML results for a specific platform."""
    seen = set()
    out = []
    plat = PLATFORMS[platform_name]

    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S
    ):
        href = m.group(1)
        title_raw = re.sub(r"<[^>]+>", "", m.group(2)).strip()

        uddg = re.search(r"uddg=([^&\"]+)", href)
        if not uddg:
            continue
        real_url = unquote(uddg.group(1))

        id_m = plat["url_re"].search(real_url)
        if not id_m:
            continue
        file_id = id_m.group(1)
        if file_id in seen:
            continue
        seen.add(file_id)

        view_url = plat["view"].format(id=file_id)

        # Build name from URL hash fragment (mega), filename in URL, or title
        name = None
        if platform_name == "mega" and id_m.group(2):
            name = unquote(id_m.group(2).replace("+", " "))

        if not name:
            # Try to get filename from URL path
            url_parts = real_url.rstrip("/").split("/")
            for part in reversed(url_parts):
                if "." in part and len(part) > 4 and part != file_id:
                    name = unquote(part.replace("+", " "))
                    break

        if not name:
            name = unquote(title_raw)

        # Clean: remove platform suffixes, junk
        name = re.sub(r"\s*[-–|]\s*(MediaFire|MEGA|1fichier|Workupload|GoFile|Catbox|Bayfiles)\s*$", "", name, flags=re.I).strip()
        name = re.sub(r"\s*[-–|]?\s*files?\.(?:catbox\.moe|mega\.nz)\s*$", "", name, flags=re.I).strip()
        name = re.sub(r"^(PDF|ZIP|RAR|MP4|MP3|EXE|7Z|ISO|EPUB|TXT|DOC)\s+", "", name, flags=re.I).strip()

        # Skip junk
        if not name or len(name) < 3 or _JUNK.search(name):
            continue

        out.append({"name": name, "url": view_url, "hash": file_id, "platform": platform_name.upper()})

    return out


async def _flare_ddg(query, platform_name, timeout_sec=30):
    """Single platform DDG search via FlareSolverr."""
    dork = PLATFORMS[platform_name]["dork"]
    full_query = f"{dork} {query}"
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
    return _extract_results(html, platform_name)


class FileHostSearch:
    _name = "FileHost"

    def __init__(self):
        self.BASE_URL = ""
        self.LIMIT = None

    async def search(self, query, page, limit):
        start_time = time.time()
        per = limit or 10
        page_num = max(int(page or 1), 1)

        # Search all platforms concurrently
        tasks = [_flare_ddg(query, p) for p in PLATFORMS]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge and deduplicate
        results = []
        seen_hashes = set()
        for r in all_results:
            if isinstance(r, list):
                for item in r:
                    if item["hash"] not in seen_hashes:
                        seen_hashes.add(item["hash"])
                        results.append(item)

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
