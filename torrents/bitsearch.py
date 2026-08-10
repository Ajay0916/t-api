import re
import time
import aiohttp
from bs4 import BeautifulSoup
from helper.html_scraper import Scraper
from constants.base_url import BITSEARCH


class Bitsearch:
    _name = "Bit Search"
    def __init__(self):
        self.BASE_URL = BITSEARCH
        self.LIMIT = None

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
                    total_pages = (
                        int(
                            soup.select(
                                "body > main > div.container.mt-2 > div > div:nth-child(1) > div > span > b"
                            )[0].text
                        )
                        / 20
                    )  # !20 search result available on each page
                    total_pages = (
                        total_pages + 1
                        if type(total_pages) == float
                        else total_pages
                        if int(total_pages) > 0
                        else total_pages + 1
                    )

                    current_page = int(
                        soup.find("div", class_="pagination")
                        .find("a", class_="active")
                        .text
                    )
                    my_dict["current_page"] = current_page
                    my_dict["total_pages"] = int(total_pages)
                except:
                    ...
                return my_dict
        except:
            return None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/search?q={}&page={}".format(query, page)
            return await self.parser_result(start_time, url, session)

    async def parser_result(self, start_time, url, session):
        html = await Scraper().get_all_results(session, url)
        results = self._parser(html)
        if results is not None:
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results
        return results

    async def trending(self, category, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/trending"
            return await self.parser_result(start_time, url, session)
