import re
import time
import aiohttp
from urllib.parse import quote as requests_quote
from bs4 import BeautifulSoup
from helper.html_scraper import Scraper
from constants.base_url import TORRENTDOWNLOAD

TRACKERS = [
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://tracker.leechers-paradise.org:6969/announce",
    "udp://9.rarbg.to:2710/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
]


class TorrentDownloads:
    _name = "Torrent Download"

    def __init__(self):
        self.BASE_URL = TORRENTDOWNLOAD
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
                    if len(td) != 5:
                        continue
                    link = td[0].find("a", href=True)
                    if not link:
                        continue
                    m = re.search(r"^/([A-Fa-f0-9]{32,40})/", link["href"])
                    if not m:
                        continue
                    name = td[0].get_text(" ", strip=True)
                    info_hash = m.group(1)
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": td[2].get_text(strip=True),
                            "date": td[1].get_text(strip=True),
                            "seeders": td[3].get_text(strip=True),
                            "leechers": td[4].get_text(strip=True),
                            "hash": info_hash,
                            "magnet": self._magnet(info_hash, name),
                            "url": self.BASE_URL + link["href"],
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    page_nums = []
                    for a in soup.select('a[href*="&p="]'):
                        m = re.search(r"[?&]p=(\d+)", a["href"])
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
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/search?q={}&p={}".format(query, page)
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
                    url = self.BASE_URL + "/search?q={}&p={}".format(query, page)
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
