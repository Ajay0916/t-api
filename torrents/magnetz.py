import re
import time
import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.html_scraper import Scraper
from constants.base_url import MAGNETZ


class Magnetz:
    _name = "Magnetz"

    def __init__(self):
        self.BASE_URL = MAGNETZ
        self.LIMIT = None

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                my_dict = {"data": []}
                for card in soup.select("article.result-card"):
                    name_el = card.select_one(".result-card__name a")
                    if not name_el:
                        continue
                    name = name_el.get_text(" ", strip=True)
                    url = name_el["href"]
                    if url.startswith("/"):
                        url = self.BASE_URL + url
                    magnet_el = card.select_one('a[href^="magnet:"]')
                    magnet = magnet_el["href"] if magnet_el else None
                    hash_match = re.search(
                        r"([{a-f\d,A-F\d}]{32,40})\b", magnet or ""
                    )
                    get_text = lambda el: el.get_text(strip=True) if el else None
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": get_text(card.select_one(".meta-chip--size")),
                            "seeders": get_text(
                                card.select_one(".meta-chip--seeders")
                            ),
                            "leechers": get_text(
                                card.select_one(".meta-chip--leechers")
                            ),
                            "category": get_text(
                                card.select_one(".meta-chip--type")
                            ),
                            "hash": hash_match.group(0) if hash_match else None,
                            "magnet": magnet,
                            "url": url,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    page_nums = []
                    for a in soup.select('a[href*="page="]'):
                        m = re.search(r"[?&]page=(\d+)", a["href"])
                        if m:
                            page_nums.append(int(m.group(1)))
                    if page_nums:
                        my_dict["total_pages"] = max(page_nums)
                except:
                    ...
                return my_dict
        except:
            return None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/search?query={}&page={}".format(query, page)
            return await self.parser_result(
                start_time, url, session, page=page, query=query
            )

    async def parser_result(self, start_time, url, session, page=1, query=None):
        html = await Scraper().get_all_results(session, url)
        results = self._parser(html)
        if results is not None:
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
                    url = self.BASE_URL + "/search?query={}&page={}".format(
                        query, page
                    )
                    html = await Scraper().get_all_results(session, url)
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
