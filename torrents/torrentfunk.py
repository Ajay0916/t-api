import re
import time

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.html_scraper import Scraper
from constants.base_url import TORRENTFUNK
from helper.trackers import build_magnet


class TorrentFunk:
    _name = "Torrent Funk"
    def __init__(self):
        self.BASE_URL = TORRENTFUNK
        self.LIMIT = None

    def _parser(self, htmls, idx=1):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                list_of_urls = []
                my_dict = {"data": []}

                for tr in soup.find_all("tr"):
                    td = tr.find_all("td", recursive=False)
                    if len(td) < 7:
                        continue
                    if not (
                        td[0].get("class")
                        and td[0]["class"][0] in ("tv1", "tv2")
                    ):
                        continue
                    name_link = td[0].find("a")
                    if name_link is None:
                        continue
                    name = name_link.text
                    url = name_link["href"]
                    if not url.startswith("http"):
                        url = self.BASE_URL + url
                    m = re.search(r"/torrent/(\d+)/", url)
                    date = td[1].text
                    size = td[2].text
                    seeders = td[3].text
                    leechers = td[4].text
                    uploader = td[5].text
                    list_of_urls.append(url)
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": size,
                            "date": date,
                            "seeders": seeders,
                            "leechers": leechers,
                            "uploader": uploader if uploader else None,
                            "torrent": (
                                "https://ft.t0r.space/tor/{}.torrent".format(m.group(1))
                                if m
                                else None
                            ),
                            "url": url,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    page_nums = []
                    for a in soup.select('a[href*="/all/torrents/"]'):
                        m = re.search(
                            r"/all/torrents/[^/]+/(\d+)\.html", a.get("href", "")
                        )
                        if m:
                            page_nums.append(int(m.group(1)))
                    if page_nums:
                        my_dict["total_pages"] = max(page_nums)
                except:
                    ...
                return my_dict, list_of_urls
        except:
            return None, None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/all/torrents/{}/{}.html".format(query, page)
            return await self.parser_result(
                start_time, url, session, idx=1, page=page, query=query
            )

    async def parser_result(self, start_time, url, session, idx=1, page=1, query=None):
        htmls = await Scraper().get_all_results(session, url)
        result, urls = self._parser(htmls, idx)
        if result:
            results = result
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            if query is not None:
                results["current_page"] = page
                while len(results["data"]) < self.LIMIT:
                    try:
                        total_pages = results.get("total_pages", page)
                    except:
                        break
                    if page >= total_pages:
                        break
                    if page >= 25:
                        break
                    page += 1
                    url = self.BASE_URL + "/all/torrents/{}/{}.html".format(
                        query, page
                    )
                    htmls = await Scraper().get_all_results(session, url)
                    result, urls = self._parser(htmls, idx)
                    if result is None or len(result["data"]) == 0:
                        break
                    for obj in result["data"]:
                        results["data"].append(obj)
                    results["current_page"] = page
                    if result.get("total_pages"):
                        results["total_pages"] = result["total_pages"]
                    results["time"] = time.time() - start_time
                    results["total"] = len(results["data"])
                results["data"] = results["data"][0 : self.LIMIT]
                results["total"] = len(results["data"])
            return results
        return result

    async def trending(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL
            return await self.parser_result(start_time, url, session)

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            if not category:
                url = self.BASE_URL + "/movies/recent.html"
            else:
                if category == "apps":
                    category = "software"
                elif category == "tv":
                    category = "television"
                elif category == "books":
                    category = "ebooks"
                url = self.BASE_URL + "/{}/recent.html".format(category)
            return await self.parser_result(start_time, url, session)
