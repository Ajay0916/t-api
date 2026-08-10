import asyncio
import hashlib
import re
import time
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup

from constants.base_url import ZOOQLE
from constants.headers import HEADER_AIO
from helper.asyncioPoliciesFix import decorator_asyncio_fix

TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://9.rarbg.to:2710/announce",
    "udp://tracker.leechers-paradise.org:6969/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.qu.ax:6969/announce",
]


def build_magnet(info_hash, name):
    dn = quote(name)
    tr = "".join("&tr={}".format(quote(t)) for t in TRACKERS)
    return "magnet:?xt=urn:btih:{}&dn={}{}".format(info_hash, dn, tr)


def extract_info_hash(raw):
    try:
        idx = raw.find(b"4:info")
        if idx == -1:
            return None
        start = idx + 6
        if raw[start : start + 1] != b"d":
            return None
        depth = 0
        pos = start
        while pos < len(raw):
            c = raw[pos : pos + 1]
            if c in (b"d", b"l"):
                depth += 1
                pos += 1
            elif c == b"e":
                depth -= 1
                pos += 1
                if depth == 0:
                    return hashlib.sha1(raw[start:pos]).hexdigest().upper()
            elif c == b"i":
                end = raw.find(b"e", pos)
                if end == -1:
                    return None
                pos = end + 1
            elif c in b"0123456789":
                end = pos
                while raw[end : end + 1] in b"0123456789":
                    end += 1
                length = int(raw[pos:end])
                pos = end + 1 + length
            else:
                pos += 1
        return None
    except Exception:
        return None


class Zooqle:
    _name = "Zooqle"

    def __init__(self):
        self.BASE_URL = ZOOQLE
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _individual(self, session, url, obj):
        try:
            async with session.get(url, headers=HEADER_AIO) as res:
                html = await res.text()
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "wp-content/uploads" in href and href.lower().endswith(".torrent"):
                    obj["torrent"] = href
                    break
        except Exception:
            pass

    @decorator_asyncio_fix
    async def _magnet(self, session, torrent_url, obj):
        try:
            async with session.get(torrent_url, headers=HEADER_AIO) as res:
                raw = await res.read()
            info_hash = extract_info_hash(raw)
            if info_hash:
                obj["hash"] = info_hash
                obj["magnet"] = build_magnet(info_hash, obj["name"])
        except Exception:
            pass

    def _parser(self, html, page, start_time):
        try:
            soup = BeautifulSoup(html, "html.parser")
            my_dict = {"data": []}
            for art in soup.find_all("article"):
                h = art.select_one(".entry-title")
                link = h.find("a") if h else None
                if not link:
                    continue
                name = link.get_text(strip=True)
                if not name:
                    continue
                t = art.select_one(".entry-date, time")
                date = (
                    t.get("datetime")
                    if t is not None and t.name == "time"
                    else (t.get_text(strip=True) if t is not None else "")
                )
                my_dict["data"].append(
                    {
                        "name": name,
                        "size": None,
                        "date": date,
                        "seeders": None,
                        "leechers": None,
                        "uploader": "",
                        "hash": None,
                        "magnet": None,
                        "torrent": None,
                        "url": link["href"],
                    }
                )
                if self.LIMIT and len(my_dict["data"]) >= self.LIMIT:
                    break
            pages = []
            for a in soup.select("a.page-numbers"):
                m = re.search(r"/page/(\d+)/", a.get("href", ""))
                if m:
                    pages.append(int(m.group(1)))
            my_dict["current_page"] = page
            my_dict["total_pages"] = max(pages) if pages else 1
            my_dict["time"] = time.time() - start_time
            my_dict["total"] = len(my_dict["data"])
            return my_dict
        except Exception:
            return None

    @decorator_asyncio_fix
    async def search(self, query, page, limit):
        self.LIMIT = limit
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            url = "{}?s={}&paged={}".format(self.BASE_URL, quote(query), page)
            async with session.get(url, headers=HEADER_AIO) as res:
                html = await res.text()
            result = self._parser(html, page, start_time)
            if result is None:
                return None
            data = result["data"]
            await asyncio.gather(
                *[
                    self._individual(session, item["url"], item)
                    for item in data
                ]
            )
            await asyncio.gather(
                *[
                    self._magnet(session, item["torrent"], item)
                    for item in data
                    if item.get("torrent")
                ]
            )
            return result
