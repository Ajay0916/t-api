import asyncio
import hashlib
import re
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup

from constants.base_url import PIMPMYMIND
from constants.headers import HEADER_AIO, AIO_TIMEOUT
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.trackers import build_magnet


def extract_info_hash(raw):
    try:
        idx = raw.find(b"4:info")
        if idx == -1:
            return None, None
        start = idx + 6
        if raw[start : start + 1] != b"d":
            return None, None
        depth = 0
        pos = start
        info_end = None
        while pos < len(raw):
            c = raw[pos : pos + 1]
            if c in (b"d", b"l"):
                depth += 1
                pos += 1
            elif c == b"e":
                depth -= 1
                pos += 1
                if depth == 0:
                    info_end = pos
                    break
            elif c == b"i":
                end = raw.find(b"e", pos)
                if end == -1:
                    return None, None
                pos = end + 1
            elif c in b"0123456789":
                end = pos
                while raw[end : end + 1] in b"0123456789":
                    end += 1
                length = int(raw[pos:end])
                pos = end + 1 + length
            else:
                pos += 1
        if info_end is None:
            return None, None
        info = raw[start:info_end]
        info_hash = hashlib.sha1(info).hexdigest().upper()
        total = sum(int(x) for x in re.findall(rb"6:lengthi(\d+)e", info))
        return info_hash, total or None
    except Exception:
        return None, None


class PimpMyMind:
    _name = "PimpMyMind"

    def __init__(self):
        self.BASE_URL = PIMPMYMIND
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _individual(self, session, url, obj, sem):
        async with sem:
            try:
                async with session.get(url, headers=HEADER_AIO, timeout=AIO_TIMEOUT) as res:
                    html = await res.text()
                soup = BeautifulSoup(html, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "wp-content/uploads" in href and href.lower().endswith(".torrent"):
                        obj["torrent"] = href
                        break
            except Exception:
                pass

    @staticmethod
    def _readable_size(num):
        size = float(num)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024 or unit == "TB":
                if unit == "B":
                    return "{} B".format(int(size))
                return "{:.2f} {}".format(size, unit)
            size /= 1024
        return ""

    @decorator_asyncio_fix
    async def _magnet(self, session, torrent_url, obj, sem):
        async with sem:
            try:
                async with session.get(torrent_url, headers=HEADER_AIO, timeout=AIO_TIMEOUT) as res:
                    raw = await res.read()
                info_hash, total_size = extract_info_hash(raw)
                if info_hash:
                    obj["hash"] = info_hash
                    obj["magnet"] = build_magnet(info_hash, obj["name"])
                if total_size:
                    obj["size"] = self._readable_size(total_size)
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
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            return await self._paginate(
                session,
                lambda p: "{}?s={}&paged={}".format(
                    self.BASE_URL, quote(query), p
                ),
                page,
                start_time,
            )

    @decorator_asyncio_fix
    async def recent(self, category, page, limit):
        self.LIMIT = limit
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            return await self._paginate(
                session,
                lambda p: (
                    "{}/page/{}/".format(self.BASE_URL, p)
                    if p > 1
                    else self.BASE_URL
                ),
                page,
                start_time,
            )

    @decorator_asyncio_fix
    async def _paginate(self, session, url_fn, page, start_time):
        async def _fetch_page(p):
            try:
                async with session.get(
                    url_fn(p), headers=HEADER_AIO, timeout=AIO_TIMEOUT
                ) as res:
                    return await res.text()
            except Exception:
                return None

        async def _enrich(items):
            sem = asyncio.Semaphore(10)
            await asyncio.gather(
                *[
                    self._individual(session, item["url"], item, sem)
                    for item in items
                ]
            )
            await asyncio.gather(
                *[
                    self._magnet(session, item["torrent"], item, sem)
                    for item in items
                    if item.get("torrent")
                ]
            )

        html = await _fetch_page(page)
        if html is None:
            return None
        result = self._parser(html, page, start_time)
        if result is None:
            return None
        await _enrich(result["data"])
        while len(result["data"]) < self.LIMIT:
            try:
                total_pages = result.get("total_pages") or page
            except:
                break
            if page >= total_pages or page >= 25:
                break
            page += 1
            html = await _fetch_page(page)
            if html is None:
                break
            nxt = self._parser(html, page, start_time)
            if nxt is None or len(nxt["data"]) == 0:
                break
            await _enrich(nxt["data"])
            result["data"].extend(nxt["data"])
            if nxt.get("total_pages"):
                result["total_pages"] = nxt["total_pages"]
            result["time"] = time.time() - start_time
            result["total"] = len(result["data"])
        result["data"] = result["data"][0 : self.LIMIT]
        result["total"] = len(result["data"])
        return result
