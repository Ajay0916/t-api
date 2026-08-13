import asyncio
import os
import re
import time
from urllib.parse import quote, urlencode

import aiohttp
from bs4 import BeautifulSoup

from helper.session import get_connector

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
FLARESOLVERR_ENRICH = (os.getenv("FLARESOLVERR_ENRICH") or "1").strip().lower() not in ("0", "false", "no")
_RUTRACKER_USER = os.getenv("RUTRACKER_USERNAME", "").strip()
_RUTRACKER_PASS = os.getenv("RUTRACKER_PASSWORD", "").strip()
ENRICH_CAP = 6
_SESSION = "rutracker-tapi"
_SEARCH_TIMEOUT = aiohttp.ClientTimeout(total=60)
_ENRICH_TIMEOUT = aiohttp.ClientTimeout(total=45)

_RU_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}

_login_done = False
_login_lock = asyncio.Lock()


class RuTracker:
    """RuTracker search via a self-hosted Flaresolverr instance.

    RuTracker is behind a Cloudflare JS challenge AND requires login for
    search, so plain HTTP clients cannot use it. Flaresolverr solves the
    challenge with a headless browser; we then log in once through the same
    session (cookies persist) and scrape tracker.php. Top results are
    enriched with magnet links from their topic pages.
    """

    _name = "RuTracker"

    def __init__(self):
        self.BASE_URL = "https://rutracker.org"
        self.LIMIT = None

    @staticmethod
    def _int(value):
        try:
            return int(str(value).replace(",", "").strip() or 0)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_date(raw):
        raw = (raw or "").strip()
        m = re.search(r"(\d{1,2})-([А-Яа-я]{3})-(\d{2})", raw)
        if not m:
            return raw
        day, mon, yr = m.groups()
        num = _RU_MONTHS.get(mon.lower(), 0)
        if not num:
            return raw
        return "20{}-{:02d}-{:02d}".format(yr, num, int(day))

    async def _flaresolverr(self, payload, timeout):
        async with aiohttp.ClientSession(
            connector=get_connector(), connector_owner=False, trust_env=True
        ) as session:
            async with session.post(
                f"{FLARESOLVERR_URL}/v1", json=payload, timeout=timeout
            ) as res:
                data = await res.json(content_type=None)
        solution = data.get("solution") or {}
        if solution.get("status") != 200:
            return None
        html = solution.get("response") or ""
        if "Just a moment" in html or "cf-chl" in html:
            return None
        return html

    async def _fetch_html(self, url, timeout):
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 55000,
            "session": _SESSION,
        }
        return await self._flaresolverr(payload, timeout)

    async def _do_login(self):
        payload = {
            "cmd": "request.post",
            "url": "https://rutracker.org/forum/login.php",
            "postData": urlencode(
                {
                    "login_username": _RUTRACKER_USER,
                    "login_password": _RUTRACKER_PASS,
                    "login": "Вход",
                    "redirect": "index.php",
                }
            ),
            "maxTimeout": 55000,
            "session": _SESSION,
        }
        html = await self._flaresolverr(payload, _SEARCH_TIMEOUT)
        return bool(html) and 'name="login_username"' not in html

    async def _ensure_login(self):
        global _login_done
        if _login_done:
            return True
        if not _RUTRACKER_USER or not _RUTRACKER_PASS:
            return False
        async with _login_lock:
            if _login_done:
                return True
            try:
                ok = await self._do_login()
            except Exception:
                return False
            if ok:
                _login_done = True
            return ok

    def _parse_rows(self, html):
        results = []
        soup = BeautifulSoup(html, "html.parser")
        for tr in soup.select("table.forumline tbody tr"):
            name_el = tr.select_one(".row4 .wbr .med")
            if not name_el:
                continue
            name = name_el.get_text(" ", strip=True)
            link = name_el.get("href") or ""
            m = re.search(r"t=(\d+)", link)
            if not m or not name:
                continue
            tid = m.group(1)
            size_el = tr.select_one("a.small.tr-dl.dl-stub")
            size = ""
            if size_el:
                size = size_el.get_text(" ", strip=True)
                sm = re.search(r"(\d+(?:[.,]\d+)?\s*(?:B|KB|MB|GB|TB))", size, re.I)
                if sm:
                    size = sm.group(1)
            cat_el = tr.select_one(".row1 .f-name .gen")
            seeds_el = tr.select_one("b.seedmed")
            peers_el = tr.select_one("td.row4.leechmed.bold")
            date_el = tr.select_one("td.row4 p")
            dl_el = tr.select_one("td.row4.small.number-format")
            results.append(
                {
                    "tid": tid,
                    "name": name,
                    "size": size,
                    "date": self._format_date(date_el.get_text(" ", strip=True) if date_el else ""),
                    "seeders": self._int(seeds_el.get_text(strip=True) if seeds_el else ""),
                    "leechers": self._int(peers_el.get_text(strip=True) if peers_el else ""),
                    "downloads": self._int(dl_el.get_text(strip=True) if dl_el else ""),
                    "category": cat_el.get_text(" ", strip=True) if cat_el else "",
                    "url": "{}/forum/viewtopic.php?t={}".format(self.BASE_URL, tid),
                    "torrent": "{}/forum/dl.php?t={}".format(self.BASE_URL, tid),
                }
            )
        return results

    async def _magnet(self, tid, sem):
        async with sem:
            try:
                html = await self._fetch_html(
                    "{}/forum/viewtopic.php?t={}".format(self.BASE_URL, tid),
                    _ENRICH_TIMEOUT,
                )
            except Exception:
                return None
            if not html:
                return None
            soup = BeautifulSoup(html, "html.parser")
            a = soup.select_one('a[href*="magnet:?xt=urn:btih:"]')
            if not a:
                return None
            href = a.get("href") or ""
            m = re.search(r"btih:([a-fA-F0-9]{40})", href)
            if not m:
                return None
            return {"hash": m.group(1).upper(), "magnet": href}

    async def search(self, query, page, limit):
        global _login_done
        if not (await self._ensure_login()):
            return None
        start_time = time.time()
        self.LIMIT = limit or None
        try:
            page = max(int(page or 1) - 1, 0)
        except (TypeError, ValueError):
            page = 0
        url = "{}/forum/tracker.php?nm={}&start={}".format(
            self.BASE_URL, quote(query), page * 50
        )
        try:
            html = await self._fetch_html(url, _SEARCH_TIMEOUT)
        except Exception:
            return None
        if not html:
            return None
        if 'name="login_username"' in html:
            _login_done = False
            if not (await self._ensure_login()):
                return None
            try:
                html = await self._fetch_html(url, _SEARCH_TIMEOUT)
            except Exception:
                return None
            if not html:
                return None
        raw = self._parse_rows(html)
        if self.LIMIT:
            raw = raw[: self.LIMIT]
        extras = []
        if raw and FLARESOLVERR_ENRICH:
            sem = asyncio.Semaphore(2)
            enrich_n = min(len(raw), ENRICH_CAP)
            extras = await asyncio.gather(
                *(self._magnet(row["tid"], sem) for row in raw[:enrich_n]),
                return_exceptions=True,
            )
        results = []
        for idx, row in enumerate(raw):
            extra = (
                extras[idx]
                if idx < len(extras) and isinstance(extras[idx], dict)
                else None
            )
            results.append(
                {
                    "name": row["name"],
                    "size": row["size"],
                    "date": row["date"],
                    "seeders": row["seeders"],
                    "leechers": row["leechers"],
                    "downloads": row["downloads"],
                    "uploader": "",
                    "category": row["category"],
                    "url": row["url"],
                    "torrent": row["torrent"],
                    "hash": (extra or {}).get("hash"),
                    "magnet": (extra or {}).get("magnet"),
                }
            )
        return {
            "data": results,
            "current_page": page + 1,
            "total_pages": 1,
            "time": time.time() - start_time,
            "total": len(results),
        }
