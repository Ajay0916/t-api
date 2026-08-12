import asyncio
import re
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import LIMETORRENT
from constants.headers import HEADER_AIO, AIO_TIMEOUT

HOSTS = [
    LIMETORRENT,
    "https://www.limetorrents.lol",
    "https://www.limetorrents.info",
    "https://www.limetorrents.net",
    "https://www.limetorrents.cc",
]


class Limetorrent:
    _name = "Lime Torrents"
    def __init__(self):
        self.BASE_URL = LIMETORRENT
        self.LIMIT = None

    async def _fetch_page(self, session, path):
        for host in HOSTS:
            htmls = await Scraper().get_all_results(session, host + path)
            if htmls and htmls[0]:
                self.BASE_URL = host
                return htmls
        return None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                async with session.get(url, headers=HEADER_AIO, timeout=AIO_TIMEOUT) as res:
                    html = await res.text(encoding="ISO-8859-1")
                    soup = BeautifulSoup(html, "html.parser")
                    try:
                        a_tag = soup.find_all("a", class_="csprite_dltorrent")
                        obj["torrent"] = a_tag[0]["href"]
                        obj["magnet"] = a_tag[-1]["href"]
                        obj["hash"] = re.search(
                            r"([{a-f\d,A-F\d}]{32,40})\b", obj["magnet"]
                        ).group(0)
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

    def _parser(self, htmls, idx=0):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                list_of_urls = []
                my_dict = {"data": []}

                for tr in soup.find_all("tr")[idx:]:
                    td = tr.find_all("td")
                    if len(td) != 6 or not td[0].select_one(".tt-name"):
                        continue
                    name = td[0].get_text(strip=True)
                    url = self.BASE_URL + td[0].find_all("a")[-1]["href"]
                    list_of_urls.append(url)
                    added_on_and_category = td[1].get_text(strip=True)
                    date = (added_on_and_category.split("-")[0]).strip()
                    category = (added_on_and_category.split("in")[-1]).strip()
                    size = td[2].text
                    seeders = td[3].text
                    leechers = td[4].text
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": size,
                            "date": date,
                            "category": category if category != date else None,
                            "seeders": seeders,
                            "leechers": leechers,
                            "url": url,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    div = soup.find("div", class_="search_stat")
                    current_page = int(div.find("span", class_="active").text)
                    total_page = int((div.find_all("a"))[-2].text)
                    if current_page > total_page:
                        total_page = current_page
                    my_dict["current_page"] = current_page
                    my_dict["total_pages"] = total_page
                except Exception:
                    ...
                return my_dict, list_of_urls
        except Exception:
            return None, None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            path = "/search/all/{}//{}".format(quote(query), page)
            return await self.parser_result(
                start_time, path, session, idx=0, page=page, query=query
            )

    async def parser_result(self, start_time, path, session, idx=0, page=1, query=None):
        htmls = await self._fetch_page(session, path)
        if htmls is None:
            return None
        result, urls = self._parser(htmls, idx)
        if result is not None:
            results = await self._get_torrent(result, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            if query is not None:
                results["current_page"] = page
                while len(results["data"]) < self.LIMIT:
                    try:
                        total_pages = results.get("total_pages", page)
                    except Exception:
                        break
                    if page >= total_pages:
                        break
                    if page >= 25:
                        break
                    page += 1
                    path = "/search/all/{}//{}".format(quote(query), page)
                    htmls = await self._fetch_page(session, path)
                    if htmls is None:
                        break
                    result, urls = self._parser(htmls, idx)
                    if result is None or len(result["data"]) == 0:
                        break
                    res = await self._get_torrent(result, session, urls)
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
        return result

    async def trending(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            path = "/top100"
            return await self.parser_result(start_time, path, session)

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            if not category:
                path = "/latest100"
            else:
                category = (category).capitalize()
                if category == "Apps":
                    category = "Applications"
                elif category == "Tv":
                    category = "TV-shows"
                path = "/browse-torrents/{}/date/{}/".format(
                    category, page
                )
            return await self.parser_result(start_time, path, session)
