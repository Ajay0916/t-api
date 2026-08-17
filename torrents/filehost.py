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
        "url_re": re.compile(r"(?:mega\.nz|mega\.co\.nz)/file/([a-zA-Z0-9]+)(?:#([a-zA-Z0-9]+))?"),
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
        "dork": "site:1fichier.com/",
        "url_re": re.compile(r"1fichier\.com/([a-zA-Z0-9]+)"),
        "view": "https://1fichier.com/{id}",
    },
    "bayfiles": {
        "dork": "site:bayfiles.com/file",
        "url_re": re.compile(r"bayfiles\.com/file/([a-zA-Z0-9]+)"),
        "view": "https://bayfiles.com/file/{id}",
    },
}

# Junk titles to skip (homepage, about pages, etc.)
_JUNK_TITLES = {
    "", "mediafire", "file sharing and storage made simple", "files.catbox.moe",
    "1fichier.com: cloud storage", "catbox", "catbox tools", "workupload",
    "workupload - are you a human?", "gofile - the free file sharing platform",
    "bayfiles", "mega", "mega.nz",
}


def _clean_title(raw, file_id):
    """Clean and validate a title."""
    name = raw.strip()
    # Remove common suffixes
    name = re.sub(r"\s*[-–|]\s*(MediaFire|MEGA|1fichier|Workupload|GoFile|Catbox|Bayfiles)\s*$", "", name, flags=re.I).strip()
    # If junk or too short, generate from file_id
    if not name or name.lower() in _JUNK_TITLES or len(name) < 4:
        return None
    return name


def _extract_results(html):
    """Extract file links from DDG HTML results across all platforms."""
    seen = set()
    out = []

    # Find result blocks: title + snippet + url
    result_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.S,
    )

    for m in result_pattern.finditer(html):
        href = m.group(1)
        title_raw = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        snippet = re.sub(r"<[^>]+>", "", m.group(3)).strip()[:200]

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

            view_url = plat_info["view"].format(id=file_id)

            # Build name: try URL filename > title > snippet > generate
            name = None

            # From URL path (e.g., mega uses #filename after hash)
            if plat_name == "mega" and "#" in real_url:
                url_name = unquote(real_url.split("#", 1)[1].replace("+", " "))
                if url_name and len(url_name) > 3:
                    name = url_name

            # From title
            if not name:
                name = _clean_title(unquote(title_raw), file_id)

            # From snippet (often has filename info)
            if not name:
                # Look for quoted filename in snippet
                snip_file = re.search(r'["\']([^"\']+\.[a-z]{2,4})["\']', snippet, re.I)
                if snip_file:
                    name = unquote(snip_file.group(1))
                else:
                    # First meaningful part of snippet
                    first_line = snippet.split(".")[0].split(" - ")[0].strip()
                    if first_line and len(first_line) > 5:
                        name = first_line

            # Final fallback
            if not name:
                if plat_name == "catbox":
                    name = file_id  # e.g., "abc123.pdf"
                else:
                    name = f"{plat_name.upper()}: {file_id[:16]}"

            out.append({
                "name": name,
                "url": view_url,
                "hash": file_id,
                "platform": plat_name.upper(),
            })
            break

    return out


async def _flare_ddg_search(query, timeout_sec=30):
    """Search via DuckDuckGo HTML through FlareSolverr."""
    dork = _build_dork()
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


def _build_dork():
    parts = [info["dork"] for info in PLATFORMS.values()]
    return " OR ".join(parts)


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
