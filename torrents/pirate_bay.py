import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote

import aiohttp

from constants.base_url import PIRATEBAY
from constants.headers import HEADER_AIO, AIO_TIMEOUT
from helper.html_scraper import Scraper
from helper.plain_curl import fetch_plain
from helper.session import get_connector
from helper.trackers import build_magnet, build_torrent_url

# apibay.org (the JSON API) is globally dead, so TPB is scraped from its
# HTML mirrors. The VPS has working IPv6 and these mirrors serve real pages
# over v6 while v4 is often challenged/blackholed, so v6 is tried first.
HOSTS = [PIRATEBAY, "https://piratebay.party", "https://thepiratebay10.org"]

_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_SHORT_DATE_RE = re.compile(r"(\d{1,2})-(\d{1,2})\s*(\d{4})")
_HASH_RE = re.compile(r"xt=urn:btih:([a-fA-F0-9]{40})")
_PAGE_RE = re.compile(r"/search/[^/]+/(\d+)/")


def _category(text):
    t = (text or "").lower()
    if t.startswith("audio"):
        return "Audio"
    if t.startswith("video"):
        return "TV" if "tv" in t else "Movies"
    if t.startswith("application"):
        return "Apps"
    if t.startswith("game"):
        return "Games"
    if t.startswith("porn"):
        return "Porn"
    if t.startswith("other"):
        return "Books" if "book" in t else "Other"
    return None


def _format_date(text):
    text = (text or "").replace("\xa0", " ").strip()
    m = _ISO_DATE_RE.search(text)
    if m:
        year, month, day = m.groups()
    else:
        m = _SHORT_DATE_RE.search(text)
        if m:
            month, day, year = m.groups()
        else:
            low = text.lower()
            now = datetime.utcnow()
            if low.startswith("today"):
                return now.strftime("%Y-%m-%d")
            if low.startswith(("y-day", "yesterday")):
                return (now - timedelta(days=1)).strftime("%Y-%m-%d")
            m = re.search(r"(\d+)\s*(min|hour|day)s?\s*ago", low)
            if m:
                n = int(m.group(1))
                unit = m.group(2)
                if unit == "min":
                    delta = timedelta(minutes=n)
                elif unit == "hour":
                    delta = timedelta(hours=n)
                else:
                    delta = timedelta(days=n)
                return (now - delta).strftime("%Y-%m-%d")
            m = re.match(r"(\d{1,2})-(\d{1,2})(?:\s+\d{1,2}:\d{2})?$", text)
            if not m:
                return ""
            month, day = m.groups()
            year = now.year
    try:
        return "{}-{:02d}-{:02d}".format(year, int(month), int(day))
    except ValueError:
        return ""



class PirateBay:
    _name = "Pirate Bay"

    def __init__(self):
        self.BASE_URL = PIRATEBAY
        self.LIMIT = None

    @staticmethod
    def _valid_page(html):
        return html is not None and ("searchResult" in html or "magnet:?" in html)

    def _parse_rows(self, html, base_url):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        results = []
        for row in soup.select("table#searchResult tr"):
            tds = row.find_all("td")
            if len(tds) < 5:
                continue
            name_a = None
            magnet = None
            for a in row.find_all("a", href=True):
                href = a["href"]
                if name_a is None and "/torrent/" in href:
                    name_a = a
                if magnet is None and href.startswith("magnet:"):
                    magnet = href
            if name_a is None or magnet is None:
                continue
            name = name_a.get_text(strip=True)
            if not name:
                continue
            m = _HASH_RE.search(magnet)
            if not m:
                continue
            info_hash = m.group(1).lower()
            rights = row.select("td[align='right']")
            size = rights[0].get_text(" ", strip=True).replace("\xa0", " ")
            seeders = rights[1].get_text(strip=True) if len(rights) > 1 else 0
            leechers = rights[2].get_text(strip=True) if len(rights) > 2 else 0
            url = name_a["href"]
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = base_url.rstrip("/") + url
            cat_td = row.find("td", class_="vertTh")
            results.append(
                {
                    "name": name,
                    "size": size,
                    "date": _format_date(
                        tds[2].get_text(" ", strip=True) if len(tds) > 2 else ""
                    ),
                    "seeders": seeders,
                    "leechers": leechers,
                    "category": _category(
                        cat_td.get_text(strip=True) if cat_td else None
                    ),
                    "uploader": tds[-1].get_text(strip=True),
                    "url": url,
                    "hash": info_hash,
                    "magnet": build_magnet(info_hash, name),
                    "torrent": build_torrent_url(info_hash, name),
                }
            )
            if self.LIMIT and len(results) >= self.LIMIT:
                break
        return results

    @staticmethod
    def _total_pages(html):
        try:
            pages = [int(p) for p in _PAGE_RE.findall(html)]
            return max(pages) if pages else 1
        except (TypeError, ValueError):
            return 1

    async def _fetch(self, url):
        body = await fetch_plain(url, timeout=12, family=6)
        if body:
            return body
        body = await fetch_plain(url, timeout=12, family=4)
        if body:
            return body
        try:
            async with aiohttp.ClientSession(
                connector=get_connector(), connector_owner=False, trust_env=True
            ) as session:
                htmls = await Scraper().get_all_results(session, url)
            if htmls and htmls[0]:
                return htmls[0]
        except Exception:
            pass
        return None

    async def _results(self, urls, start_time):
        for url in urls:
            html = await self._fetch(url)
            if not self._valid_page(html):
                continue
            base_url = re.match(r"https?://[^/]+", url).group(0)
            results = self._parse_rows(html, base_url)
            return {
                "data": results,
                "current_page": 1,
                "total_pages": self._total_pages(html),
                "time": time.time() - start_time,
                "total": len(results),
            }
        return None

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        urls = [
            "{}/search/{}/{}/99/0".format(host, quote(query), page)
            for host in HOSTS
        ]
        return await self._results(urls, start_time)

    async def trending(self, category, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        urls = ["{}/top/100".format(host) for host in HOSTS]
        return await self._results(urls, start_time)

    async def recent(self, category, page, limit):
        start_time = time.time()
        self.LIMIT = limit
        urls = ["{}/recent".format(host) for host in HOSTS]
        return await self._results(urls, start_time)
