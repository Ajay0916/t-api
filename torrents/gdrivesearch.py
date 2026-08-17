import asyncio
import re
import time
from urllib.parse import quote

from helper.plain_curl import fetch_plain

# Google Dorking: search for public Google Drive files/folders
_GOOGLE_SEARCH = "https://www.google.com/search?q={query}&num={num}&start={start}"
_DRIVE_PATTERN = re.compile(
    r'(?:(?:drive\.google\.com/(?:file/d|open\?id|folderview\?id)=|'
    r'docs\.google\.com/(?:uc\?id|open\?id)=))([a-zA-Z0-9_-]{20,})'
)
_TITLE_PATTERN = re.compile(r'<h3[^>]*>(.*?)</h3>', re.S)


def _clean_title(raw):
    """Strip HTML tags from Google search result title."""
    text = re.sub(r'<[^>]+>', '', raw)
    text = text.replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"')
    return text.strip()


def _extract_drive_id(url):
    """Extract Google Drive file/folder ID from URL."""
    m = _DRIVE_PATTERN.search(url)
    return m.group(1) if m else None


def _drive_direct_link(file_id):
    """Generate direct download link for a Drive file."""
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def _drive_view_link(file_id):
    """Generate view link for a Drive file."""
    return f"https://drive.google.com/file/d/{file_id}/view"


class GDriveSearch:
    _name = "GDrive Search"

    def __init__(self):
        self.BASE_URL = "https://drive.google.com"
        self.LIMIT = None

    async def search(self, query, page, limit):
        start_time = time.time()
        per = limit or 10
        page_num = max(int(page or 1), 1)
        start = (page_num - 1) * per

        # Build Google dork query for public Drive files
        dork = f'site:drive.google.com "{query}"'
        url = _GOOGLE_SEARCH.format(
            query=quote(dork),
            num=min(per + 5, 20),
            start=start,
        )

        html = await fetch_plain(url, timeout=12)
        if not html:
            return None

        # Extract Drive IDs and titles from search results
        results = []
        seen = set()

        # Find all Drive links in the HTML
        for match in _DRIVE_PATTERN.finditer(html):
            file_id = match.group(1)
            if file_id in seen:
                continue
            seen.add(file_id)

            # Try to find the title from surrounding HTML
            pos = match.start()
            chunk = html[max(0, pos - 500):pos + 200]
            title_match = _TITLE_PATTERN.search(chunk)
            title = _clean_title(title_match.group(1)) if title_match else f"GDrive: {file_id[:12]}..."

            results.append({
                "name": title,
                "url": _drive_view_link(file_id),
                "torrent": _drive_direct_link(file_id),
                "download": _drive_direct_link(file_id),
                "hash": file_id,
                "category": "GDrive",
                "size": "",
            })

            if limit and len(results) >= limit:
                break

        total_pages = max(1, page_num + 1) if len(results) >= per else page_num

        return {
            "data": results[:limit] if limit else results,
            "current_page": page_num,
            "total_pages": total_pages,
            "time": time.time() - start_time,
            "total": len(results),
        }

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
