import asyncio
import re
import time
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import TORRENTFUNK
from constants.headers import HEADER_AIO

TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://9.rarbg.to:2710/announce",
    "udp://tracker.leechers-paradise.org:6969/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.qu.ax:6969/announce",
]


def build_magnet(info_hash, name):
    dn = quote(name)
    tr = "".join("&tr={}".format(quote(t)) for t in TRACKERS)
    return "magnet:?xt=urn:btih:{}&dn={}{}".format(info_hash, dn, tr)


class TorrentFunk:
    _name = "Torrent Funk"
    def __init__(self):
        self.BASE_URL = TORRENTFUNK
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj):
        try:
            async with session.get(url, headers=HEADER_AIO) as res:
                html = await res.text(encoding="ISO-8859-1")
                soup = BeautifulSoup(html, "html.parser")
                try:
                    torrent_a = soup.find(
                        "a", href=lambda h: h and h.lower().endswith(".torrent")
                    )
                    if torrent_a:
                        torrent = torrent_a["href"]
                        if torrent.startswith("/"):
                            torrent = self.BASE_URL + torrent
                        obj["torrent"] = torrent
                    m = re.search(r"([a-fA-F0-9]{40})\b", html)
                    if m:
                        obj["hash"] = m.group(1)
                        obj["magnet"] = build_magnet(m.group(1), obj.get("name") or "")
                except Exception:
                    ...
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

    def _parser(self, htmls, idx=1):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                list_of_urls = []
                my_dict = {"data": []}

                for table in soup.select("table.tmain.tf-torrentlist"):
                    if "z3" in (table.get("class") or []):
                        continue
                    for tr in table.select("tr")[idx:]:
                        td = tr.find_all("td")
                        name_link = td[0].find("a") if td else None
                        if name_link is None:
                            continue
                        name = name_link.text
                        url = name_link["href"]
                        if not url.startswith("http"):
                            url = self.BASE_URL + url
                        if len(td) >= 6:
                            date = td[1].text
                            size = td[2].text
                            seeders = td[3].text
                            leechers = td[4].text
                            uploader = td[5].text
                        else:
                            date = size = seeders = leechers = uploader = None
                        list_of_urls.append(url)
                        my_dict["data"].append(
                            {
                                "name": name,
                                "size": size,
                                "date": date,
                                "seeders": seeders,
                                "leechers": leechers,
                                "uploader": uploader if uploader else None,
                                "url": url,
                            }
                        )
                        if len(my_dict["data"]) == self.LIMIT:
                            break
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                return my_dict, list_of_urls
        except:
            return None, None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/all/torrents/{}/{}.html".format(query, page)
            return await self.parser_result(start_time, url, session, idx=1)

    async def parser_result(self, start_time, url, session, idx=1):
        htmls = await Scraper().get_all_results(session, url)
        result, urls = self._parser(htmls, idx)
        if result:
            results = await self._get_torrent(result, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results
        return result

    async def trending(self, category, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL
            return await self.parser_result(start_time, url, session)

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession() as session:
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
