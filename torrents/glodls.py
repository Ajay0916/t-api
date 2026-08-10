import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import aiohttp

from constants.base_url import GLODLS
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


def format_size(size):
    try:
        size = float(size)
    except (TypeError, ValueError):
        return str(size)
    if size <= 0:
        return "0"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return "{:.2f} {}".format(size, units[i])


class Glodls:
    _name = "Glodls"

    def __init__(self):
        self.BASE_URL = GLODLS
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _fetch(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADER_AIO) as res:
                return await res.text(encoding="ISO-8859-1")

    def _parser(self, xml_text, page, start_time):
        end = xml_text.rfind("</rss>")
        if end != -1:
            xml_text = xml_text[: end + len("</rss>")]
        root = ET.fromstring(xml_text)
        results = []
        for item in root.iter("item"):
            def field(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else ""

            title = field("title")
            info_hash = field("info_hash")
            if not title:
                continue
            results.append(
                {
                    "name": title,
                    "size": format_size(field("size")),
                    "date": field("pubDate"),
                    "seeders": field("seeders"),
                    "leechers": field("leechers"),
                    "category": field("category"),
                    "uploader": "",
                    "hash": info_hash,
                    "magnet": build_magnet(info_hash, title) if info_hash else None,
                    "torrent": None,
                    "url": self.BASE_URL + field("link"),
                }
            )
        if self.LIMIT:
            results = results[: self.LIMIT]
        total_pages = page + 1 if len(results) >= 50 else page
        return {
            "data": results,
            "current_page": page,
            "total_pages": total_pages,
            "time": time.time() - start_time,
            "total": len(results),
        }

    async def _request(self, url, page):
        try:
            xml_text = await self._fetch(url)
            return self._parser(xml_text, page, time.time())
        except Exception:
            return None

    async def search(self, query, page, limit):
        self.LIMIT = limit
        url = (
            self.BASE_URL
            + "/rss.xml?type=search&search={}&page={}".format(quote(query), page)
        )
        return await self._request(url, page)

    async def trending(self, category, page, limit):
        self.LIMIT = limit
        url = self.BASE_URL + "/rss.xml?type=today"
        return await self._request(url, page)

    async def recent(self, category, page, limit):
        self.LIMIT = limit
        url = self.BASE_URL + "/rss.xml?type=today"
        return await self._request(url, page)

    async def get_torrent_by_url(self, torrent_url):
        return None
