import asyncio
import os
import re
import time
import uuid
from urllib.parse import quote

import aiohttp
from helper.plain_curl import fetch_plain
from helper.session import close_flare_session_async, get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import TORLOCK

HOSTS = [TORLOCK]
from constants.headers import HEADER_AIO, AIO_TIMEOUT

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
_SESSION_TTL = 300.0
_sid = None
_sid_created = 0.0
_flare_lock = asyncio.Lock()


def _get_sid():
    global _sid, _sid_created
    now = time.time()
    if not _sid or now - _sid_created > _SESSION_TTL:
        old = _sid
        _sid = "torlock-{}".format(uuid.uuid4().hex[:10])
        _sid_created = now
        # Replacing the session leaks the old browser unless destroyed.
        close_flare_session_async(old, FLARESOLVERR_URL)
    return _sid


class Torlock:
    _name = "Tor Lock"
    def __init__(self):
        self.BASE_URL = TORLOCK
        self.LIMIT = None
        self._flare_cookies = {}
        self._flare_ua = ""

    @decorator_asyncio_fix
    async def _flaresolverr(self, payload, timeout):
        async with _flare_lock:
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
        return solution

    async def _flare_page(self, url):
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000,
            "session": _get_sid(),
        }
        sol = await self._flaresolverr(payload, aiohttp.ClientTimeout(total=65))
        if not sol:
            return None
        self._flare_cookies = {
            c.get("name"): c.get("value")
            for c in (sol.get("cookies") or [])
            if c.get("name") and c.get("value")
        }
        self._flare_ua = sol.get("userAgent") or ""
        return sol.get("response") or None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                headers = (
                    {**HEADER_AIO, "User-Agent": self._flare_ua}
                    if self._flare_ua
                    else HEADER_AIO
                )
                kwargs = {"headers": headers, "timeout": AIO_TIMEOUT}
                if self._flare_cookies:
                    kwargs["cookies"] = self._flare_cookies
                async with session.get(url, **kwargs) as res:
                    html = await res.text(encoding="ISO-8859-1")
                    soup = BeautifulSoup(html, "html.parser")
                    try:
                        magnet_a = soup.find(
                            "a", href=lambda h: h and h.startswith("magnet:")
                        )
                        torrent_a = soup.find(
                            "a", href=lambda h: h and h.lower().endswith(".torrent")
                        )
                        if magnet_a:
                            obj["magnet"] = magnet_a["href"]
                            m = re.search(r"([a-fA-F0-9]{32,40})\b", obj["magnet"])
                            if m:
                                obj["hash"] = m.group(1)
                        if torrent_a:
                            obj["torrent"] = torrent_a["href"]
                        try:
                            poster = soup.find("img", class_="img-responsive")
                            if poster:
                                obj["poster"] = poster["src"]
                        except Exception:
                            ...
                        imgs = soup.select(".tab-content img.img-fluid")
                        if imgs and len(imgs) > 0:
                            obj["screenshot"] = [img["src"] for img in imgs]
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

    def _parser(self, htmls, idx=0):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                list_of_urls = []
                my_dict = {"data": []}

                for tr in soup.find_all("tr")[idx:]:
                    td = tr.find_all("td")
                    if len(td) == 0:
                        continue
                    # New layout: the row's name link is a.tl-name; the first
                    # <a> in the cell is the category badge (e.g. /movies.html).
                    # Fall back to any /torrent/ link for the older layout.
                    name_a = td[0].find("a", class_="tl-name")
                    if name_a is None:
                        name_a = td[0].find(
                            "a", href=lambda h: h and "/torrent/" in h
                        )
                    if name_a is None:
                        continue
                    name = name_a.get_text(strip=True)
                    if name != "":
                        url = name_a["href"]
                        if url == "":
                            break
                        if not url.startswith("http"):
                            url = self.BASE_URL + url
                        list_of_urls.append(url)
                        size = td[2].get_text(strip=True)
                        date = td[1].get_text(strip=True)
                        seeders = td[3].get_text(strip=True)
                        leechers = td[4].get_text(strip=True)
                        my_dict["data"].append(
                            {
                                "name": name,
                                "size": size,
                                "date": date,
                                "seeders": seeders,
                                "leechers": leechers,
                                "url": url,
                            }
                        )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    ul = soup.find("ul", class_="pagination")
                    tpages = ul.find_all("a")[-2].text
                    current_page = (
                        (ul.find("li", class_="active")).find("span").text.split(" ")[0]
                    )
                    my_dict["current_page"] = int(current_page)
                    my_dict["total_pages"] = int(tpages)
                except Exception:
                    my_dict["current_page"] = None
                    my_dict["total_pages"] = None
                return my_dict, list_of_urls
        except Exception:
            return None, None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/all/torrents/{}.html?sort=seeds&page={}".format(
                quote(query), page
            )
            results = await self.parser_result(start_time, url, session, idx=5)
            if results is None or not results.get("data"):
                for host in HOSTS:
                    if host == self.BASE_URL:
                        continue
                    try:
                        self.BASE_URL = host
                        url = self.BASE_URL + "/all/torrents/{}.html?sort=seeds&page={}".format(
                            quote(query), page
                        )
                        results = await self.parser_result(time.time(), url, session, idx=5)
                        if results and results.get("data"):
                            break
                    except Exception:
                        continue
                self.BASE_URL = TORLOCK
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
                url = self.BASE_URL + "/all/torrents/{}.html?sort=seeds&page={}".format(
                    quote(query), page
                )
                res = await self.parser_result(
                    start_time, url, session, idx=5
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

    async def parser_result(self, start_time, url, session, idx=0):
        htmls = await Scraper().get_all_results(session, url)
        result, urls = self._parser(htmls, idx)
        if result is None or not result.get("data"):
            # torlock serves full pages over IPv6 (VPS has IPv6 now) while the
            # v4 identity gets anti-bot stripped pages (HTTP 200, zero rows),
            # so try a v6 curl before paying for a FlareSolverr solve.
            v6_html = await fetch_plain(url, timeout=10, family=6)
            if v6_html:
                fresult, furls = self._parser([v6_html], idx)
                if fresult and fresult.get("data"):
                    result, urls = fresult, furls
        if result is None or not result.get("data"):
            # Last resort: torlock2.com is Cloudflare-fronted; solve any
            # remaining JS challenge via FlareSolverr and reparse.
            flare_html = await self._flare_page(url)
            if flare_html:
                fresult, furls = self._parser([flare_html], idx)
                if fresult and fresult.get("data"):
                    result, urls = fresult, furls
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
            if not category:
                url = self.BASE_URL
            else:
                if category == "books":
                    category = "ebooks"
                url = self.BASE_URL + "/{}.html".format(category)
            return await self.parser_result(start_time, url, session)

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            if not category:
                url = self.BASE_URL + "/fresh.html"
            else:
                if category == "books":
                    category = "ebooks"
                url = self.BASE_URL + "/{}/{}/added/desc.html".format(category, page)
            return await self.parser_result(start_time, url, session)

    #! Maybe impelment Search By Category in Future
