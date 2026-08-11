import asyncio
import hashlib
import re
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import YOURBITTORRENT
from constants.headers import HEADER_AIO, AIO_TIMEOUT
from helper.trackers import build_magnet


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


class YourBittorrent:
    _name = "Your BitTorrent"
    def __init__(self):
        self.BASE_URL = YOURBITTORRENT
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                async with session.get(
                    url, headers=HEADER_AIO, timeout=AIO_TIMEOUT
                ) as res:
                    html = await res.text(encoding="ISO-8859-1")
                soup = BeautifulSoup(html, "html.parser")
                try:
                    torrent_a = soup.find(
                        "a", href=lambda h: h and h.lower().endswith(".torrent")
                    )
                    if torrent_a:
                        torrent = torrent_a["href"]
                        if torrent.startswith("/"):
                            torrent = self.BASE_URL + torrent
                        obj["torrent"] = torrent
                        try:
                            async with session.get(
                                torrent, headers=HEADER_AIO
                            ) as tr:
                                raw = await tr.read()
                            info_hash = extract_info_hash(raw)
                            if info_hash:
                                obj["hash"] = info_hash
                                obj["magnet"] = build_magnet(
                                    info_hash, obj.get("name") or ""
                                )
                        except Exception:
                            pass
                    try:
                        poster = soup.find("img", class_="img-fluid")
                        if poster:
                            obj["poster"] = poster["src"]
                    except Exception:
                        pass
                except Exception:
                    ...
            except Exception:
                return None

    async def _get_torrent(self, result, session, urls):
        tasks = []
        sem = asyncio.Semaphore(15)
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(
                            session, url, result["data"][idx], sem
                        )
                    )
                    tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    def _parser(self, htmls, idx=1):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                list_of_urls = []
                my_dict = {"data": []}

                for card in soup.select("a.yb-gcard")[idx:]:
                    name_el = card.select_one(".yb-gcard-name")
                    if not name_el:
                        continue
                    name = name_el.get_text(" ", strip=True)
                    url = self.BASE_URL + card["href"]
                    list_of_urls.append(url)
                    meta = card.select_one(".yb-gcard-meta")
                    size = meta.select_one(".z").get_text(strip=True) if meta and meta.select_one(".z") else None
                    seeders = meta.select_one(".s").get_text(strip=True) if meta and meta.select_one(".s") else None
                    leechers = meta.select_one(".p").get_text(strip=True) if meta and meta.select_one(".p") else None
                    seeders = re.sub(r"\D", "", seeders) if seeders else None
                    leechers = re.sub(r"\D", "", leechers) if leechers else None
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": size,
                            "date": None,
                            "seeders": seeders,
                            "leechers": leechers,
                            "url": url,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    ul = soup.find("ul", class_="pagination")
                    pages = []
                    if ul:
                        for a in ul.find_all("a", href=True):
                            m = re.search(r"page=(\d+)", a["href"])
                            if m:
                                pages.append(int(m.group(1)))
                    my_dict["total_pages"] = max(pages) if pages else None
                except:
                    my_dict["total_pages"] = None
                return my_dict, list_of_urls
        except:
            return None, None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/?v=&c=&q={}".format(quote(query))
            results = await self.parser_result(start_time, url, session, idx=0)
            if results is None:
                return None
            results["current_page"] = page
            while len(results["data"]) < self.LIMIT:
                try:
                    total_pages = results.get("total_pages") or page
                except:
                    break
                if page >= total_pages or page >= 25:
                    break
                page += 1
                url = self.BASE_URL + "/?q={}&page={}".format(quote(query), page)
                res = await self.parser_result(
                    time.time() - start_time, url, session, idx=0
                )
                if res is None or len(res["data"]) == 0:
                    break
                for obj in res["data"]:
                    results["data"].append(obj)
                results["current_page"] = page
                if res.get("total_pages"):
                    results["total_pages"] = res["total_pages"]
                results["time"] = time.time() - start_time
                results["total"] = len(results["data"])
            results["data"] = results["data"][0 : self.LIMIT]
            results["total"] = len(results["data"])
            return results

    async def parser_result(self, start_time, url, session, idx=1):
        htmls = await Scraper().get_all_results(session, url)
        result, urls = self._parser(htmls, idx)
        if result is not None:
            results = await self._get_torrent(result, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results
        return result

    async def trending(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            idx = None
            if not category:
                url = self.BASE_URL + "/top.html"
                idx = 1
            else:
                if category == "books":
                    category = "ebooks"
                url = self.BASE_URL + f"/{category}.html"
                idx = 4
            return await self.parser_result(start_time, url, session, idx)

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            idx = None
            if not category:
                url = self.BASE_URL + "/new.html"
                idx = 1
            else:
                if category == "books":
                    category = "ebooks"
                url = self.BASE_URL + f"/{category}/latest.html"
                idx = 4
            return await self.parser_result(start_time, url, session, idx)
