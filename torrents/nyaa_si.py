import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.html_scraper import Scraper
from constants.base_url import NYAASI
from helper.trackers import build_magnet

NS = {"nyaa": "https://nyaa.si/xmlns/nyaa"}


def _rss_date(value):
    try:
        return parsedate_to_datetime(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return value or None


class NyaaSi:
    _name = "Nyaa"
    def __init__(self):
        self.BASE_URL = NYAASI
        self.LIMIT = None

    def _parse_rss(self, xml_text):
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None
        results = []
        for item in root.iter("item"):
            title = item.findtext("title")
            info_hash = item.findtext("nyaa:infoHash", namespaces=NS)
            if not title or not info_hash:
                continue
            def _f(tag):
                el = item.find("nyaa:" + tag, namespaces=NS)
                return el.text if el is not None else None
            link = item.findtext("link")
            guid = item.findtext("guid")
            results.append(
                {
                    "name": title,
                    "size": _f("size"),
                    "date": _rss_date(item.findtext("pubDate")),
                    "seeders": _f("seeders"),
                    "leechers": _f("leechers"),
                    "downloads": _f("downloads"),
                    "category": _f("category"),
                    "hash": info_hash,
                    "magnet": build_magnet(info_hash, title),
                    "torrent": link,
                    "url": guid or link,
                }
            )
            if self.LIMIT and len(results) >= self.LIMIT:
                break
        return results

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")

                my_dict = {"data": []}
                for tr in (soup.find("table")).find_all("tr")[1:]:
                    td = tr.find_all("td")
                    name = td[1].find_all("a")[-1].text
                    url = td[1].find_all("a")[-1]["href"]
                    magnet_and_torrent = td[2].find_all("a")
                    magnet = magnet_and_torrent[-1]["href"]
                    torrent = self.BASE_URL + magnet_and_torrent[0]["href"]
                    size = td[3].text
                    date = td[4].text
                    seeders = td[5].text
                    leechers = td[6].text
                    downloads = td[7].text
                    category = td[0].find("a")["title"].split("-")[0].strip()
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": size,
                            "seeders": seeders,
                            "leechers": leechers,
                            "category": category,
                            "hash": re.search(
                                r"([{a-f\d,A-F\d}]{32,40})\b", magnet
                            ).group(0),
                            "magnet": magnet,
                            "torrent": torrent,
                            "url": self.BASE_URL + url,
                            "date": date,
                            "downloads": downloads,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break

                try:
                    ul = soup.find("ul", class_="pagination")
                    tpages = ul.find_all("a")[-2].text
                    current_page = (ul.find("li", class_="active")).find("a").text
                    my_dict["current_page"] = int(current_page)
                    my_dict["total_pages"] = int(tpages)
                except:
                    my_dict["current_page"] = None
                    my_dict["total_pages"] = None
                return my_dict
        except:
            return None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            rss_url = self.BASE_URL + "/?page=rss&q={}&c=0_0&f=0".format(
                quote(query)
            )
            htmls = await Scraper().get_all_results(session, rss_url)
            data = self._parse_rss(htmls[0]) if htmls and htmls[0] else None
            if data is not None:
                return {
                    "data": data,
                    "current_page": page,
                    "total_pages": 1,
                    "time": time.time() - start_time,
                    "total": len(data),
                }
            url = self.BASE_URL + "/?f=0&c=0_0&q={}&p={}".format(
                quote(query), page
            )
            return await self.parser_result(start_time, url, session)

    async def parser_result(self, start_time, url, session):
        html = await Scraper().get_all_results(session, url)
        results = self._parser(html)
        if results is not None:
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results
        return results

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            rss_url = self.BASE_URL + "/?page=rss&c=0_0&f=0"
            htmls = await Scraper().get_all_results(session, rss_url)
            data = self._parse_rss(htmls[0]) if htmls and htmls[0] else None
            if data is not None:
                return {
                    "data": data,
                    "current_page": page,
                    "total_pages": 1,
                    "time": time.time() - start_time,
                    "total": len(data),
                }
            url = self.BASE_URL
            return await self.parser_result(start_time, url, session)
