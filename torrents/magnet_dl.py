import asyncio
import re
import time
import aiohttp
from urllib.parse import quote as requests_quote
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import MAGNETDL

TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://9.rarbg.to:2710/announce",
    "udp://tracker.leechers-paradise.org:6969/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
]


class Magnetdl:
    _name = "MagnetDL"

    def __init__(self):
        self.BASE_URL = MAGNETDL
        self.LIMIT = None

    def _magnet(self, info_hash, name):
        magnet = "magnet:?xt=urn:btih:{}&dn={}".format(
            info_hash, requests_quote(name)
        )
        for tracker in TRACKERS:
            magnet += "&tr=" + requests_quote(tracker, safe=":/")
        return magnet

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
    async def _individual_scrap(self, session, url, obj):
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
                obj["magnet"] = self._magnet(info_hash, obj["name"])
        except:
            return None

    async def _get_torrent(self, result, session, urls):
        tasks = []
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(session, url, result["data"][idx])
                    )
                    tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    async def parser_result(self, start_time, url, session):
        htmls = await Scraper().get_all_results(session, url)
        results = self._parser(htmls)
        if results is not None:
            urls = [item["url"] for item in results["data"]]
            results = await self._get_torrent(results, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results
        return results

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/search/?q={}&orderby=DESC&order=seeders".format(
                query
            )
            return await self.parser_result(start_time, url, session)

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession() as session:
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
