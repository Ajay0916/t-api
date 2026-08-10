import re
import time
from urllib.parse import quote as requests_quote
import aiohttp
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import EXTRATORRENT


class ExtraTorrent:
    _name = "ext"

    def __init__(self):
        self.BASE_URL = EXTRATORRENT
        self.LIMIT = None

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                my_dict = {"data": []}
                table = soup.find("table", class_="tl")
                if table is None:
                    continue
                for tr in table.find_all("tr"):
                    td = tr.find_all("td")
                    if len(td) < 6:
                        continue
                    magnet_a = td[0].find("a", href=True)
                    name_a = td[1].find("a", href=True)
                    if not magnet_a or not name_a:
                        continue
                    magnet = magnet_a["href"]
                    if "magnet:?xt=" not in magnet:
                        continue
                    name = name_a.get_text(strip=True)
                    href = name_a["href"]
                    if not href.startswith("http"):
                        href = self.BASE_URL + href
                    obj = {
                        "name": name,
                        "size": td[3].get_text(strip=True),
                        "date": td[2].get_text(strip=True),
                        "seeders": td[4].get_text(strip=True),
                        "leechers": td[5].get_text(strip=True),
                        "url": href,
                        "magnet": magnet,
                    }
                    hash_match = re.search(r"([a-fA-F0-9]{32,40})\b", magnet)
                    if hash_match:
                        obj["hash"] = hash_match.group(1)
                    my_dict["data"].append(obj)
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                current_page = 1
                total_pages = 1
                current = soup.find("b", class_="pager_no_link")
                if current:
                    current_page = int(current.get_text(strip=True))
                pages = []
                for a in soup.find_all("a", class_="pager_link", href=True):
                    m = re.search(r"[?&]page=(\d+)", a["href"])
                    if m:
                        pages.append(int(m.group(1)))
                if pages:
                    total_pages = max(max(pages), current_page)
                my_dict["current_page"] = current_page
                my_dict["total_pages"] = total_pages
                return my_dict
        except:
            return None

    async def parser_result(self, start_time, url, session):
        htmls = await Scraper().get_all_results(session, url)
        results = self._parser(htmls)
        if results is not None:
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results
        return results

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/search/?search={}&new=1".format(
                requests_quote(query)
            )
            if page > 1:
                url += "&page={}".format(page)
            return await self.parser_result(start_time, url, session)
