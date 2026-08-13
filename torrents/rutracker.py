import asyncio
import os
import re
import time
from urllib.parse import quote_plus, urlencode

import aiohttp
from bs4 import BeautifulSoup

from helper.session import get_connector

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
FLARESOLVERR_ENRICH = (os.getenv("FLARESOLVERR_ENRICH") or "1").strip().lower() not in ("0", "false", "no")
_RUTRACKER_USER = os.getenv("RUTRACKER_USERNAME", "").strip()
_RUTRACKER_PASS = os.getenv("RUTRACKER_PASSWORD", "").strip()
# Optional pre-authenticated session cookie ("bb_session=...; bb_guid=...; ...").
# RuTracker gates logins behind a captcha from datacenter IPs, so when a cookie
# is set we skip the login POST entirely and send it with every request.
_RUTRACKER_COOKIE = os.getenv("RUTRACKER_COOKIE", "").strip()
ENRICH_CAP = 6
_SESSION = "rutracker-tapi"
_SEARCH_TIMEOUT = aiohttp.ClientTimeout(total=60)
_ENRICH_TIMEOUT = aiohttp.ClientTimeout(total=45)

# RuTracker shows a hidden quick-login form (with login_username input) in the
# header DOM of every page, so that alone can never tell logged-in from guest.
# A real login page instead contains this full-page form heading; the
# captcha variant shows a different heading on the same form.
_LOGIN_PAGE_MARK = "Введите ваше имя и пароль"
_CAPTCHA_MARK = "код подтверждения"


def _cookie_list():
    cookies = []
    for part in _RUTRACKER_COOKIE.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            cookies.append({"name": name.strip(), "value": value.strip()})
    return cookies

_RU_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}


class RuTracker:
    """RuTracker search via a self-hosted Flaresolverr instance.

    RuTracker is behind a Cloudflare JS challenge AND requires login for
    search. Flaresolverr solves the challenge with a headless browser. If
    ``RUTRACKER_COOKIE`` is set (from a manual browser login), it is sent
    with every request — no login POST needed (logins are captcha-gated
    from datacenter IPs). Otherwise the login form's ``redirect`` field
    takes us straight to the search results page in one Flaresolverr
    request. Top results are enriched with magnet links from their topic
    pages.
    """

    _name = "RuTracker"

    def __init__(self):
        self.BASE_URL = "https://rutracker.org"
        self.LIMIT = None

    @staticmethod
    def _int(value):
        # RuTracker formats counts as "12 345" (space thousands separator)
        try:
            return int(re.sub(r"[^\d]", "", str(value)))
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

    @staticmethod
    def _is_login_page(html):
        return _LOGIN_PAGE_MARK in html or _CAPTCHA_MARK in html

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
        if _RUTRACKER_COOKIE:
            payload["cookies"] = _cookie_list()
        return await self._flaresolverr(payload, timeout)

    async def _login_and_fetch(self, redirect_target, timeout):
        """Log in and land directly on ``redirect_target`` in one request."""
        payload = {
            "cmd": "request.post",
            "url": "{}/forum/login.php".format(self.BASE_URL),
            "postData": urlencode(
                {
                    "login_username": _RUTRACKER_USER,
                    "login_password": _RUTRACKER_PASS,
                    "login": "Вход",
                    "redirect": redirect_target,
                }
            ),
            "maxTimeout": 55000,
            "session": _SESSION,
        }
        return await self._flaresolverr(payload, timeout)

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
            url = "{}/forum/viewtopic.php?t={}".format(self.BASE_URL, tid)
            try:
                html = await self._fetch_html(url, _ENRICH_TIMEOUT)
            except Exception:
                return None
            if html and self._is_login_page(html) and not _RUTRACKER_COOKIE:
                # Login did not carry over; log in and land on the topic
                # page in one request instead.
                try:
                    html = await self._login_and_fetch(
                        "viewtopic.php?t={}".format(tid), _ENRICH_TIMEOUT
                    )
                except Exception:
                    return None
            if not html or self._is_login_page(html):
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
        start_time = time.time()
        self.LIMIT = limit or None
        try:
            page = max(int(page or 1) - 1, 0)
        except (TypeError, ValueError):
            page = 0
        start = page * 50
        url = "{}/forum/tracker.php?nm={}".format(self.BASE_URL, quote_plus(query))
        if start:
            url += "&start={}".format(start)
        if _RUTRACKER_COOKIE:
            try:
                html = await self._fetch_html(url, _SEARCH_TIMEOUT)
            except Exception:
                return None
        else:
            if not _RUTRACKER_USER or not _RUTRACKER_PASS:
                return None
            redirect = "tracker.php?nm={}".format(quote_plus(query))
            if start:
                redirect += "&start={}".format(start)
            try:
                html = await self._login_and_fetch(redirect, _SEARCH_TIMEOUT)
            except Exception:
                return None
        if not html or self._is_login_page(html):
            # Login page/captcha came back → auth failed (bad creds/blocked).
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
