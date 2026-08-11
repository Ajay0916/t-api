import asyncio
import re
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import TORRENTPROJECT
from constants.headers import HEADER_AIO, AIO_TIMEOUT
from helper.trackers import build_torrent_url


class TorrentProject:
    _name = "Torrent Project"
    def __init__(self):
        self.BASE_URL = TORRENTPROJECT
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                async with session.get(
                    url,
                    headers=HEADER_AIO,
                timeout=AIO_TIMEOUT,
                ) as res:
                    html = await res.text(encoding="ISO-8859-1")
                    soup = BeautifulSoup(html, "html.parser")
                    try:
                        for a in soup.find_all("a", href=True):
                            href = a["href"]
                            if "magnet:?xt=" in unquote(href):
                                if "mylink.cloud" in href:
                                    magnet = parse_qs(
                                        urlparse(href).query
                                    ).get("url", [None])[0]
                                else:
                                    m = re.search(
                                        r"magnet:\?xt=[^\"'\s<]+",
                                        unquote(href),
                                    )
                                    magnet = m.group(0) if m else None
                                if magnet:
                                    obj["magnet"] = magnet
                                    m = re.search(
                                        r"([a-fA-F0-9]{32,40})\b", magnet
                                    )
                                    if m:
                                        obj["hash"] = m.group(1)
                                        obj["torrent"] = build_torrent_url(
                                            m.group(1), obj.get("name") or ""
                                        )
                                break
                    except Exception:
                        ...
            except Exception:
                return None

    async def _get_torrent(self, result, session, urls):
        tasks = []
        sem = asyncio.Semaphore(10)
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(session, url, result["data"][idx], sem)
                    )
                    tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    def _parser(self, htmls, page=1):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                list_of_urls = []
                my_dict = {"data": []}
                similar = soup.select_one("div#similarfiles")
                rows = similar.find_all("div", recursive=False) if similar else []
                for div in rows:
                    spans = div.find_all("span")
                    if not spans or not spans[0]:
                        continue
                    a = spans[0].find("a")
                    if not a or not a.get("href", "").startswith("/t3-"):
                        continue
                    name = a.get_text(strip=True)
                    url = self.BASE_URL + a["href"]
                    list_of_urls.append(url)
                    seeders = spans[2].get_text(strip=True) if len(spans) > 2 else ""
                    leechers = spans[3].get_text(strip=True) if len(spans) > 3 else ""
                    date = spans[4].get_text(strip=True) if len(spans) > 4 else ""
                    size = spans[5].get_text(strip=True) if len(spans) > 5 else ""

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
                my_dict["current_page"] = page
                my_dict["total_pages"] = None
                return my_dict, list_of_urls
        except:
            return None, None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/?t={}&p={}".format(quote(query), page - 1)
            results = await self.parser_result(start_time, url, session, page)
            if results is None:
                return None
            results["current_page"] = page
            while len(results["data"]) < self.LIMIT:
                if page >= 25:
                    break
                page += 1
                url = self.BASE_URL + "/?t={}&p={}".format(quote(query), page - 1)
                res = await self.parser_result(
                    time.time() - start_time, url, session, page
                )
                if res is None or len(res["data"]) == 0:
                    break
                seen = {obj["url"] for obj in results["data"]}
                for obj in res["data"]:
                    if obj["url"] not in seen:
                        results["data"].append(obj)
                        seen.add(obj["url"])
                results["current_page"] = page
                results["time"] = time.time() - start_time
                results["total"] = len(results["data"])
            results["data"] = results["data"][0 : self.LIMIT]
            results["total"] = len(results["data"])
            return results

    async def parser_result(self, start_time, url, session, page=1):
        htmls = await Scraper().get_all_results(session, url)
        result, urls = self._parser(htmls, page)
        if result is not None:
            results = await self._get_torrent(result, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results
        return result
