import asyncio
import os
import re
import time

import aiohttp
from urllib.parse import quote

from constants.base_url import OCEANOFPDF
from helper.search_cache import TTLCache
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.session import get_connector

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
_flare_lock = asyncio.Lock()


class OceanofPDF:
    _name = "OceanofPDF"
    _download_cache = TTLCache(max_size=1024, ttl=21600, name="oceanofpdf_download")

    def __init__(self):
        self.BASE_URL = OCEANOFPDF
        self.LIMIT = None
        self._cookies = {}
        self._ua = ""

    @decorator_asyncio_fix
    async def _flaresolverr(self, payload, timeout):
        async with _flare_lock:
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=10, force_close=True, ssl=False),
                connector_owner=True, trust_env=True
            ) as session:
                async with session.post(
                    f"{FLARESOLVERR_URL}/v1", json=payload, timeout=timeout
                ) as res:
                    data = await res.json(content_type=None)
        solution = data.get("solution") or {}
        if solution.get("status") != 200:
            return None
        return solution

    async def _flare_get(self, url, timeout_sec=30):
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": timeout_sec * 1000,
            "session": "oceanofpdf",
        }
        return await self._flaresolverr(payload, aiohttp.ClientTimeout(total=timeout_sec + 10))

    async def _flare_post(self, url, post_data, timeout_sec=30):
        payload = {
            "cmd": "request.post",
            "url": url,
            "postData": post_data,
            "maxTimeout": timeout_sec * 1000,
            "session": "oceanofpdf",
        }
        return await self._flaresolverr(payload, aiohttp.ClientTimeout(total=timeout_sec + 10))

    async def _search_page(self, query, page):
        url = self.BASE_URL + "/?s=" + quote(query)
        if page > 1:
            url = self.BASE_URL + "/page/{}/?s={}".format(page, quote(query))
        sol = await self._flare_get(url, timeout_sec=60)
        if not sol:
            return None, None, None
        html = sol.get("response") or ""
        self._ua = sol.get("userAgent") or self._ua
        self._cookies = {
            c.get("name"): c.get("value")
            for c in (sol.get("cookies") or [])
            if c.get("name") and c.get("value")
        } or self._cookies
        return html, self._cookies, self._ua

    @staticmethod
    def _is_challenge(html):
        low = (html or "")[:2000].lower()
        return not html or "just a moment" in low or "cf-chl" in low or "attention required" in low

    def _browser_headers(self, referer=None):
        headers = {
            "User-Agent": self._ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    @staticmethod
    def _parser(html):
        out = []
        seen = set()
        for m in re.finditer(
            r'href="(https://oceanofpdf\.com/authors/[^"]+-download[^"]*)"[^>]*>([^<]{3,90})',
            html,
        ):
            url = m.group(1).split("#")[0]
            name = m.group(2).strip()
            if not name or name == "[Read more…]":
                continue
            if url in seen:
                continue
            seen.add(url)
            out.append({"name": name, "url": url, "hash": None, "magnet": None})
        return out

    @decorator_asyncio_fix
    async def _book_info(self, obj, sem, http):
        cached = self._download_cache.get(obj["url"])
        if cached:
            if cached.get("size"):
                obj["size"] = cached["size"]
            obj["torrent"] = cached["torrent"]
            obj["download"] = cached["torrent"]
            return
        async with sem:
            try:
                stage = "plain-get"
                try:
                    async with http.get(obj["url"], headers=self._browser_headers(self.BASE_URL), timeout=aiohttp.ClientTimeout(total=20)) as res:
                        html = await res.text(errors="replace")
                        if res.status == 200 and not self._is_challenge(html):
                            self._cookies.update({c.key: c.value for c in http.cookie_jar})
                        else:
                            html = ""
                except Exception:
                    html = ""
                if not html:
                    stage = "flare-get"
                    sol = await self._flare_get(obj["url"], timeout_sec=30)
                    if not sol:
                        return
                    html = sol.get("response") or ""
                    self._ua = sol.get("userAgent") or self._ua
                    self._cookies = {
                        c.get("name"): c.get("value")
                        for c in (sol.get("cookies") or [])
                        if c.get("name") and c.get("value")
                    } or self._cookies
                m = re.search(r"File Size[\s\S]{0,120}?([\d.,]+\s*(?:MB|GB|KB))\b", html, re.I)
                if m:
                    obj["size"] = m.group(1).replace(" ", "")
                fm = re.search(
                    r'name="id"\s+type="hidden"\s+value="([^"]+)"[^>]*>'
                    r'\s*<input\s+name="filename"\s+type="hidden"\s+value="([^"]+)"',
                    html,
                )
                if fm:
                    fid, fname = fm.groups()
                else:
                    fm = re.search(
                        r'name="filename"\s+type="hidden"\s+value="([^"]+)"[^>]*>'
                        r'\s*<input\s+name="id"\s+type="hidden"\s+value="([^"]+)"',
                        html,
                    )
                    if not fm:
                        return
                    fname, fid = fm.groups()

                body = ""
                stage = "plain-post"
                try:
                    async with http.post(
                        self.BASE_URL + "/Fetching_Resource.php",
                        data={"id": fid, "filename": fname},
                        headers={**self._browser_headers(obj["url"]), "Content-Type": "application/x-www-form-urlencoded"},
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as res:
                        if res.status == 200:
                            body = await res.text(errors="replace")
                except Exception:
                    pass
                if self._is_challenge(body) or "url=" not in body.lower():
                    stage = "flare-post"
                    post_sol = await self._flare_post(
                        self.BASE_URL + "/Fetching_Resource.php",
                        f"id={fid}&filename={fname}",
                        timeout_sec=30,
                    )
                    if not post_sol:
                        return
                    body = post_sol.get("response") or ""
                    self._ua = post_sol.get("userAgent") or self._ua
                    self._cookies = {
                        c.get("name"): c.get("value")
                        for c in (post_sol.get("cookies") or [])
                        if c.get("name") and c.get("value")
                    } or self._cookies
                m = re.search(
                    r'<meta[^>]*http-equiv=["\']?refresh["\']?[^>]*>',
                    body,
                    re.I,
                )
                if not m:
                    return
                u = re.search(r"url=([^\"'\s>]+)", m.group(0), re.I)
                if not u:
                    return
                dl_url = u.group(1).replace("&amp;", "&")
                obj["torrent"] = dl_url
                obj["download"] = dl_url
                self._download_cache.set(obj["url"], {"size": obj.get("size"), "torrent": dl_url})
            except Exception:
                return

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        html, cookies, ua = await self._search_page(query, page)
        if not html:
            return None
        data = self._parser(html)
        if not data:
            return None
        data = data[:limit]
        sem = asyncio.Semaphore(4)
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=10, force_close=True, ssl=False),
            cookies=self._cookies,
            connector_owner=True,
            trust_env=True,
        ) as http:
            tasks = [
                asyncio.create_task(self._book_info(obj, sem, http))
                for obj in data
            ]
            await asyncio.gather(*tasks)
        data = [d for d in data if d.get("torrent")]
        if not data:
            return None
        return {
            "data": data,
            "time": time.time() - start_time,
            "total": len(data),
            "current_page": page,
            "total_pages": page,
        }

    async def trending(self, category, page, limit):
        return None

    async def recent(self, category, page, limit):
        return None


OceanofPDF._download_cache.load()
