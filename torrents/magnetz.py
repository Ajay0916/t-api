import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.html_scraper import Scraper
from constants.base_url import MAGNETZ
from helper.trackers import build_torrent_url


class Magnetz:
    _name = "Magnetz"

    def __init__(self):
        self.BASE_URL = MAGNETZ
        self.LIMIT = None

    def _parse_rss(self, xml_text, start_time):
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None
        data = []
        for item in root.iter("item"):
            def field(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else ""

            name = field("title")
            if not name:
                continue
            size = field("{https://magnetz.eu/rss/}contentLength")
            magnet = field("{https://magnetz.eu/rss/}magnetURI")
            info_hash = field("{https://magnetz.eu/rss/}infoHash")
            if not info_hash:
                m = re.search(r"urn:btih:([a-fA-F0-9]{40})", magnet)
                info_hash = m.group(1) if m else ""
            data.append(
                {
                    "name": name,
                    "size": self._format_size(size) if size else None,
                    "date": field("pubDate"),
                    "seeders": None,
                    "leechers": None,
                    "category": None,
                    "uploader": "",
                    "hash": info_hash if info_hash else None,
                    "magnet": magnet if magnet else None,
                    "torrent": (
                        build_torrent_url(info_hash, name) if info_hash else None
                    ),
                    "url": field("link"),
                }
            )
            if self.LIMIT and len(data) >= self.LIMIT:
                break
        if not data:
            return None
        return {
            "data": data,
            "current_page": 1,
            "total_pages": 1,
            "time": time.time() - start_time,
            "total": len(data),
        }

    @staticmethod
    def _format_size(size):
        try:
            size = float(size)
        except (TypeError, ValueError):
            return str(size)
        if size <= 0:
            return "0"
        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size >= 1024 and i < len(units) - 1:
            size /= 1024
            i += 1
        return "{:.2f} {}".format(size, units[i])

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
                            "torrent": (
                                build_torrent_url(hash_match.group(0), name)
                                if hash_match
                                else None
                            ),
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
            url = self.BASE_URL + "/search?query={}&page={}".format(
                quote(query), page
            )
            return await self.parser_result(
                start_time, url, session, page=page, query=query
            )

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            htmls = await Scraper().get_all_results(session, self.BASE_URL + "/rss")
            if not htmls or not htmls[0]:
                return None
            return self._parse_rss(htmls[0], start_time)

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
                        quote(query), page
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
