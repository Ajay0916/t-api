"""downloadly.ir — WordPress course site with dl*.downloadly.ir direct links.
Fresh implementation using fetch_plain (system curl), no proxy/mirror."""
import asyncio
import re
import time
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup

import os
import aiohttp

from constants.base_url import DOWNLOADLY
from helper.logging_setup import get_logger
from helper.plain_curl import fetch_plain, _is_cf_challenge

_LOGGER = get_logger("tapi.downloadly")
_MIRROR_URL = "https://downloadlynet.ir"
_FLARE_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")

_SKIP_SLUGS = (
    "category", "tag", "page", "feed", "wp-",
    "privacy", "about", "contact", "terms",
)

_DL_RE = re.compile(r"https?://dl\d*\.downloadly\.ir/")
_NUMERIC_POST_RE = re.compile(
    r"^https?://downloadly(?:net)?\.ir/\d{4}/\d{1,2}/\d+/\d{1,2}/([^/]+)(?:/\d+)?/?$",
    re.I,
)
_HOME_CANONICAL_RE = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']https://downloadly(?:net)?\.ir/?["\']',
    re.I,
)
_HOME_TITLE_RE = re.compile(r'<title[^>]*>\s*Downloadly\s*[–-]\s*Free Software Download', re.I)
_PART_RE = re.compile(r"([\d.]+)\s*(?:گیگابایت|GB)", re.I)


def _is_wrong_post_response(url, html):
    """WordPress sometimes answers a post URL with the cached homepage."""
    path = urlsplit(url).path.rstrip("/")
    if not html or len(html) < 500 or path in ("", "/"):
        return False
    head = html[:100000]
    return bool(_HOME_CANONICAL_RE.search(head) or _HOME_TITLE_RE.search(head))


def _is_unusable_post_response(url, html):
    low = (html or "")[:5000].lower()
    return (
        _is_wrong_post_response(url, html)
        or _is_cf_challenge(html)
        or "bot verification" in low
    )


def _parse_parts(html):
    """Extract download links + Persian labels from a post page."""
    soup = BeautifulSoup(html, "html.parser")
    parts = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _DL_RE.match(href) or "/Sample/" in href or href in seen:
            continue
        seen.add(href)
        text = a.get_text(" ", strip=True)
        size_m = _PART_RE.search(text)
        size = f"{size_m.group(1)} GB" if size_m else ""
        # Convert Persian part label to English
        part_num = re.search(r"بخش\s*(\d+)", text)
        label = f"Part {part_num.group(1)}" if part_num else text[:40]
        if size:
            label += f" — {size}"
        parts.append({"url": href, "label": label, "size": size})
    return parts


class Downloadly:
    _name = "Downloadly"
    _flare_session = "downloadly_persistent"
    _flare_session_ready = False
    _flare_session_lock = asyncio.Lock()
    _flare_request_lock = asyncio.Lock()

    def __init__(self):
        self.BASE_URL = DOWNLOADLY
        self.LIMIT = None

    async def _fetch(self, url, timeout=15):
        # 1. Plain curl on primary domain
        html = await fetch_plain(url, timeout=timeout)
        _LOGGER.info("[TEMP-DL] primary url=%s bytes=%d wrong=%s challenge=%s", url, len(html or ""), _is_wrong_post_response(url, html), _is_cf_challenge(html or ""))
        if html and len(html) > 500 and not _is_unusable_post_response(url, html):
            return html
        # 2. Plain curl on mirror domain
        mirror = url.replace("downloadly.ir", "downloadlynet.ir", 1)
        html = await fetch_plain(mirror, timeout=timeout)
        _LOGGER.info("[TEMP-DL] mirror url=%s bytes=%d wrong=%s challenge=%s", url, len(html or ""), _is_wrong_post_response(url, html), _is_cf_challenge(html or ""))
        if html and len(html) > 500 and not _is_unusable_post_response(url, html):
            return html
        # 3. FlareSolverr fallback; the persistent context must not receive overlapping requests.
        async with self._flare_request_lock:
            html = await self._fetch_flare(url, timeout=max(timeout, 60))
        _LOGGER.info("[TEMP-DL] flare-session url=%s bytes=%d wrong=%s", url, len(html or ""), _is_wrong_post_response(url, html))
        if html and _is_wrong_post_response(url, html):
            # A persistent browser context can cache WordPress's homepage for
            # a post. Destroy it and try once with a clean context.
            await self._reset_flare_session()
            async with self._flare_request_lock:
                html = await self._fetch_flare(
                    url, timeout=max(timeout, 60), use_session=False
                )
            _LOGGER.info("[TEMP-DL] flare-clean url=%s bytes=%d wrong=%s", url, len(html or ""), _is_wrong_post_response(url, html))
            if html and _is_wrong_post_response(url, html):
                return None
        return html

    async def _fetch_flare(self, url, timeout=15, use_session=True):
        for attempt in range(2):
            try:
                if use_session:
                    await self._ensure_flare_session()
                payload = {
                    "cmd": "request.get",
                    "url": url,
                    "maxTimeout": timeout * 1000,
                }
                if use_session:
                    payload["session"] = self._flare_session
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{_FLARE_URL}/v1", json=payload,
                        timeout=aiohttp.ClientTimeout(total=timeout + 10),
                    ) as res:
                        data = await res.json(content_type=None)
                solution = data.get("solution") or {}
                if solution.get("status") == 200:
                    html = solution.get("response") or ""
                    if len(html) > 500:
                        return html
                message = str(data.get("message") or "").lower()
                if "session" in message and attempt == 0:
                    await self._reset_flare_session()
                    continue
            except Exception as exc:
                _LOGGER.warning("Downloadly FlareSolverr failed for %s: %s", url, exc)
        return None

    async def _ensure_flare_session(self):
        async with self._flare_session_lock:
            if self._flare_session_ready:
                return
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_FLARE_URL}/v1",
                    json={"cmd": "sessions.create", "session": self._flare_session},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as res:
                    data = await res.json(content_type=None)
            message = str(data.get("message") or "").lower()
            if data.get("status") == "ok" or "already exists" in message:
                self._flare_session_ready = True

    async def _reset_flare_session(self):
        async with self._flare_session_lock:
            self._flare_session_ready = False
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{_FLARE_URL}/v1",
                        json={"cmd": "sessions.destroy", "session": self._flare_session},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as res:
                        await res.json(content_type=None)
            except Exception:
                pass

    async def _post_page(self, url, obj, sem):
        async with sem:
            # One persistent browser context avoids repeated Cloudflare challenges.
            page = await self._fetch(url, timeout=15)
            if not page or len(page) < 1000 or _is_cf_challenge(page):
                return
            parts = _parse_parts(page)
            if not parts:
                obj["torrent"] = url
                obj["download"] = url
                return
            h1 = BeautifulSoup(page, "html.parser").select_one("h1")
            if h1:
                name = h1.get_text(" ", strip=True)
                if name:
                    obj["name"] = name
            if len(parts) > 1:
                obj["torrents"] = [
                    {
                        "quality": p["label"],
                        "type": "RAR",
                        "size": p["size"],
                        "torrent": p["url"],
                    }
                    for p in parts
                ]

    @staticmethod
    def _canonical_post_href(href, card):
        """Translate the legacy numeric listing URL to its real category URL."""
        match = _NUMERIC_POST_RE.match(href)
        if not match:
            return href
        slug = match.group(1)
        candidates = []
        for a in card.find_all("a", href=True):
            candidate = a["href"].replace("downloadlynet.ir", "downloadly.ir")
            if (
                slug.lower() in candidate.lower()
                and not _NUMERIC_POST_RE.match(candidate)
                and any(part in candidate for part in ("/elearning/", "/download/software/", "/software/", "/mobile/"))
            ):
                candidates.append(candidate.split("#", 1)[0].rstrip("/") + "/")
        if candidates:
            return max(candidates, key=lambda item: item.count("/"))
        return "https://downloadly.ir/elearning/video-tutorials/{}/".format(slug)

    @staticmethod
    def _parse_grid(html, seen, limit=None):
        """Parse w-grid-item divs from any page."""
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for div in soup.find_all("div", class_=lambda c: c and "w-grid-item" in c):
            h2 = div.find("h2", class_=lambda c: c and "entry-title" in c)
            a = h2.find("a", href=True) if h2 else None
            if not a:
                continue
            href = a["href"].replace("downloadlynet.ir", "downloadly.ir")
            href = Downloadly._canonical_post_href(href, div)
            if href in seen or any(s in href for s in _SKIP_SLUGS):
                continue
            name = a.get_text(" ", strip=True)
            if not name:
                continue
            seen.add(href)
            results.append({"name": name, "url": href, "category": "Courses"})
            if limit and len(results) >= limit:
                break
        return results

    async def search(self, query, page, limit):
        start_time = time.time()
        seen = set()
        all_results = []
        want = limit if limit else 300
        max_pages = 1 if want <= 15 else 6
        page_numbers = list(range(1, max_pages + 1))

        for chunk_start in range(0, len(page_numbers), 3):
            if len(all_results) >= want:
                break
            chunk = page_numbers[chunk_start:chunk_start + 3]
            pages = await asyncio.gather(*[
                self._fetch(
                    "{}/?s={}".format(self.BASE_URL, quote(query)) + ("&paged={}".format(n) if n > 1 else ""),
                    timeout=15,
                )
                for n in chunk
            ])
            got_new = False
            for html in pages:
                if not html:
                    continue
                more = self._parse_grid(html, seen)
                if more:
                    got_new = True
                all_results.extend(more)
            if not got_new:
                break

        if not all_results:
            return {"data": [], "current_page": page, "total_pages": 1,
                    "time": time.time() - start_time, "total": 0}

        # Post pages intermittently serve the homepage to datacenter IPs.
        # Return the reliable search listing immediately; the bot links the
        # primary post page, which works from the user's browser.
        for item in all_results:
            item["torrent"] = item["url"]
            item["download"] = item["url"]

        total_pages = min(max_pages, max(1, (len(all_results) + 9) // 10))
        return {"data": all_results[:limit] if limit else all_results,
                "current_page": page, "total_pages": total_pages,
                "time": time.time() - start_time, "total": len(all_results)}

    async def resolve_parts(self, post_url):
        """Fetch download links from a post page via FlareSolverr."""
        html = await self._fetch(post_url, timeout=20)
        if not html or len(html) < 1000 or _is_cf_challenge(html):
            return []
        return _parse_parts(html)

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None
