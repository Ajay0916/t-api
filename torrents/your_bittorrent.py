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

HOSTS = [YOURBITTORRENT, "https://yourbittorrent2.com"]
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

    async def _direct_html(self, session, url):
        """Temporary diagnostic wrapper for YBT host responses."""
        try:
            async with session.get(
                url,
                headers=HEADER_AIO,
                timeout=AIO_TIMEOUT,
            ) as res:
                html = await res.text(encoding="ISO-8859-1", errors="replace")
            print(
                f"[TEMP-YBT] direct http={res.status} bytes={len(html)} "
                f"cards={html.count('yb-gcard')} cf={'cf-chl' in html.lower()} "
                f"title={(re.search(r'<title>(.*?)</title>', html[:5000], re.I|re.S).group(1)[:60].replace(chr(10),' ') if re.search(r'<title>(.*?)</title>', html[:5000], re.I|re.S) else '')!r} "
                f"url={url[:100]}",
                flush=True,
            )
            return html if res.status < 400 else None
        except Exception as exc:
            print(f"[TEMP-YBT] direct failed type={type(exc).__name__} url={url[:100]}", flush=True)
            return None

    async def _jina_html(self, session, url):
        """Last-resort reader fetch that returns the original HTML."""
        target = "https://r.jina.ai/" + url
        try:
            async with session.get(
                target,
                headers={
                    "User-Agent": HEADER_AIO["User-Agent"],
                    "Accept": "text/html,*/*",
                    "X-Return-Format": "html",
                },
                timeout=aiohttp.ClientTimeout(total=45),
            ) as res:
                if res.status >= 400:
                    print(f"[TEMP-YBT] jina http={res.status} url={url[:100]}", flush=True)
                    return None
                html = await res.text(encoding="utf-8", errors="replace")
            print(
                f"[TEMP-YBT] jina ok bytes={len(html)} url={url[:100]}",
                flush=True,
            )
            return html.lstrip().lower().startswith("<!doctype html") and html or None
        except Exception as exc:
            print(f"[TEMP-YBT] jina failed type={type(exc).__name__} url={url[:100]}", flush=True)
            return None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                try:
                    async with session.get(
                        url, headers=HEADER_AIO, timeout=AIO_TIMEOUT
                    ) as res:
                        if res.status >= 400:
                            html = None
                        else:
                            html = await res.text(encoding="ISO-8859-1")
                except Exception:
                    html = None
                if not html:
                    html = await self._jina_html(session, url)
                if not html:
                    return None
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
                            session, url, obj, sem
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
                except Exception:
                    my_dict["total_pages"] = None
                return my_dict, list_of_urls
        except Exception:
            return None, None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
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
                except Exception:
                    break
                if page >= total_pages or page >= 25:
                    break
                page += 1
                url = self.BASE_URL + "/?q={}&page={}".format(quote(query), page)
                res = await self.parser_result(
                    start_time, url, session, idx=0
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

    async def _fetch_page(self, session, url):
        # Rotate across mirrors when the pinned host stops responding, then
        # pin the first host that returns content (same pattern as 1337x/ext).
        path = url.split(self.BASE_URL, 1)[-1] if self.BASE_URL in url else url
        start = HOSTS.index(self.BASE_URL) if self.BASE_URL in HOSTS else 0
        for i in range(len(HOSTS)):
            host = HOSTS[(start + i) % len(HOSTS)]
            html = await self._direct_html(session, host + path)
            htmls = [html] if html else []
            if htmls and htmls[0]:
                self.BASE_URL = host
                return htmls
        html = await self._jina_html(session, url)
        if html:
            return [html]
        return None

    async def parser_result(self, start_time, url, session, idx=1):
        htmls = await self._fetch_page(session, url)
        result, urls = self._parser(htmls, idx)
        if result is not None:
            results = await self._get_torrent(result, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results
        return result

    async def trending(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
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
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
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
