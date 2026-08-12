import re
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.html_scraper import Scraper
from constants.base_url import BITSEARCH

HOSTS = [BITSEARCH, "https://bitsearch.to"]


class Bitsearch:
    _name = "Bit Search"
    def __init__(self):
        self.BASE_URL = BITSEARCH
        self.LIMIT = None

    async def _fetch_page(self, session, path):
        for host in HOSTS:
            htmls = await Scraper().get_all_results(session, host + path)
            if htmls and htmls[0]:
                self.BASE_URL = host
                return htmls
        return None

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")

                my_dict = {"data": []}
                for link in soup.select('a[href^="/torrent/"]'):
                    card = link
                    for _ in range(6):
                        if card.parent is None:
                            break
                        card = card.parent
                        if "rounded-lg" in (card.get("class") or []):
                            break
                    if "rounded-lg" not in (card.get("class") or []):
                        continue
                    name = link.get_text(strip=True)
                    url = self.BASE_URL + link["href"]
                    magnet_el = card.select_one('a[href^="magnet:"]')
                    torrent_el = card.select_one('a[href^="/download/torrent/"]')
                    if not magnet_el or not torrent_el:
                        continue
                    magnet = magnet_el["href"]
                    torrent = self.BASE_URL + torrent_el["href"]
                    stat_groups = card.select(".flex.flex-wrap.items-center.gap-4")
                    category = size = date = downloads = None
                    if stat_groups:
                        outer = [
                            s for s in stat_groups[0].find_all("span", recursive=False)
                        ]
                        if len(outer) >= 3:
                            category = outer[0].get_text(strip=True)
                            size = outer[1].get_text(strip=True)
                            date = outer[2].get_text(strip=True)
                    seeders_el = card.select_one(".text-green-600 span.font-medium")
                    leechers_el = card.select_one(".text-red-600 span.font-medium")
                    downloads_el = card.select_one(".text-blue-600 span.font-medium")
                    seeders = seeders_el.get_text(strip=True) if seeders_el else None
                    leechers = leechers_el.get_text(strip=True) if leechers_el else None
                    downloads = (
                        downloads_el.get_text(strip=True) if downloads_el else None
                    )
                    hash_match = re.search(
                        r"([{a-f\d,A-F\d}]{32,40})\b", magnet
                    )
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": size,
                            "seeders": seeders,
                            "leechers": leechers,
                            "category": category,
                            "hash": hash_match.group(0) if hash_match else None,
                            "magnet": magnet,
                            "torrent": torrent,
                            "url": url,
                            "date": date,
                            "downloads": downloads,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    page_nums = []
                    for a in soup.select('a[href*="page="]'):
                        m = re.search(r"page=(\d+)", a["href"])
                        if m:
                            page_nums.append(int(m.group(1)))
                    if page_nums:
                        my_dict["total_pages"] = max(page_nums)
                except Exception:
                    ...
                return my_dict
        except Exception:
            return None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            path = "/search?q={}&page={}".format(quote(query), page)
            return await self.parser_result(
                start_time, path, session, page=page, query=query
            )

    async def parser_result(self, start_time, path, session, page=1, query=None):
        html = await self._fetch_page(session, path)
        if html is None:
            return None
        results = self._parser(html)
        if results is not None:
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
                    path = "/search?q={}&page={}".format(quote(query), page)
                    html = await self._fetch_page(session, path)
                    if html is None:
                        break
                    res = self._parser(html)
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
        return results

    async def trending(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/trending"
            return await self.parser_result(start_time, url, session)
