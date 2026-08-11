import asyncio
import re
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import MAGNETDL
from helper.trackers import build_magnet, build_torrent_url


class Magnetdl:
    _name = "MagnetDL"

    def __init__(self):
        self.BASE_URL = MAGNETDL
        self.LIMIT = None

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                my_dict = {"data": []}
                for tr in soup.find_all("tr"):
                    td = tr.find_all("td")
                    if len(td) != 7:
                        continue
                    name = td[1].get_text(strip=True)
                    link = td[1].find("a", href=True)
                    if not name or not link:
                        continue
                    href = link["href"]
                    if not href.startswith("http"):
                        href = self.BASE_URL + href
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": td[4].get_text(strip=True),
                            "date": td[2].get_text(strip=True),
                            "category": td[3].get_text(strip=True),
                            "seeders": td[5].get_text(strip=True),
                            "leechers": td[6].get_text(strip=True),
                            "url": href,
                            "hash": None,
                            "magnet": None,
                            "torrent": None,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                return my_dict
        except:
            return None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                html = await Scraper().get_all_results(session, url)
                if not html or not html[0]:
                    return
                soup = BeautifulSoup(html[0], "html.parser")
                dt = soup.find("dt", string=re.compile(r"Info Hash", re.I))
                if not dt:
                    return
                dd = dt.find_next_sibling("dd")
                info_hash = dd.get_text(strip=True) if dd else None
                if info_hash:
                    obj["hash"] = info_hash
                    obj["magnet"] = build_magnet(info_hash, obj["name"])
                    obj["torrent"] = build_torrent_url(info_hash, obj["name"])
            except:
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

    async def parser_result(self, start_time, url, session, page=1, query=None):
        htmls = await Scraper().get_all_results(session, url)
        results = self._parser(htmls)
        if results is not None:
            urls = [item["url"] for item in results["data"]]
            results = await self._get_torrent(results, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            if query is not None:
                results["current_page"] = page
                while len(results["data"]) < self.LIMIT:
                    page += 1
                    url = self.BASE_URL + "/search/?q={}&orderby=DESC&order=seeders&page={}".format(
                        quote(query), page
                    )
                    htmls = await Scraper().get_all_results(session, url)
                    res = self._parser(htmls)
                    if res is None or len(res["data"]) == 0:
                        break
                    urls = [item["url"] for item in res["data"]]
                    res = await self._get_torrent(res, session, urls)
                    for obj in res["data"]:
                        results["data"].append(obj)
                    results["current_page"] = page
                    results["time"] = time.time() - start_time
                    results["total"] = len(results["data"])
                    if len(res["data"]) < 10 or page >= 25:
                        break
                results["data"] = results["data"][0 : self.LIMIT]
                results["total"] = len(results["data"])
            return results
        return results

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/search/?q={}&orderby=DESC&order=seeders&page={}".format(
                quote(query), page
            )
            return await self.parser_result(
                start_time, url, session, page=page, query=query
            )

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            if not category:
                url = self.BASE_URL + "/download/movies/"
            else:
                if category == "books":
                    category = "e-books"
                elif category == "apps":
                    category = "software"
                url = self.BASE_URL + "/download/{}/".format(category)
            return await self.parser_result(start_time, url, session)
