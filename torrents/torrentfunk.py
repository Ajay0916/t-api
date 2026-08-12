import asyncio
import re
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import TORRENTFUNK
from constants.headers import HEADER_AIO, AIO_TIMEOUT
from helper.trackers import build_magnet
from torrents.your_bittorrent import extract_info_hash


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
                    if not td:
                        continue
                    td0_class = td[0].get("class") or []
                    tr_class = tr.get("class") or []
                    if td0_class and td0_class[0] in ("tv1", "tv2"):
                        if len(td) < 7:
                            continue
                        name_link = td[0].find("a")
                        if name_link is None:
                            continue
                        name = name_link.text
                        url = name_link["href"]
                        date = td[1].get_text(strip=True)
                        size = td[2].get_text(strip=True)
                        seeders = td[3].get_text(strip=True)
                        leechers = td[4].get_text(strip=True)
                        uploader = td[5].get_text(strip=True)
                    elif tr_class and tr_class[0] in ("a", "b") and "tv" in td0_class:
                        name_link = td[0].find("a")
                        if name_link is None:
                            continue
                        name = name_link.get_text(" ", strip=True)
                        url = name_link["href"]
                        date = td[1].get_text(strip=True) if len(td) > 1 else ""
                        size = td[2].get_text(strip=True) if len(td) > 2 else ""
                        seeders = td[3].get_text(strip=True) if len(td) > 3 else ""
                        leechers = td[4].get_text(strip=True) if len(td) > 4 else ""
                        uploader = td[5].get_text(strip=True) if len(td) > 5 else ""
                    else:
                        continue
                    if url.startswith("http"):
                        # SEO-spam rows link to external pages (t0r.space CDN)
                        # with fake names/seeders - real rows are relative.
                        continue
                    url = self.BASE_URL + url
                    m = re.search(r"/torrent/(\d+)", url)
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
                return my_dict, list_of_urls
        except Exception:
            return None, None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, obj, sem):
        async with sem:
            try:
                torrent = obj.get("torrent")
                if not torrent:
                    return None
                raw = None
                for attempt in range(2):
                    try:
                        async with session.get(
                            torrent,
                            headers=HEADER_AIO,
                            timeout=AIO_TIMEOUT,
                            allow_redirects=True,
                        ) as tr:
                            raw = await tr.read()
                        break
                    except Exception:
                        if attempt == 1:
                            return None
                        await asyncio.sleep(1)
                if not raw:
                    return None
                info_hash = extract_info_hash(raw)
                if info_hash:
                    obj["hash"] = info_hash
                    obj["magnet"] = build_magnet(
                        info_hash, obj.get("name") or ""
                    )
            except Exception:
                return None

    async def _get_torrent(self, result, session):
        tasks = []
        sem = asyncio.Semaphore(10)
        for obj in result["data"]:
            task = asyncio.create_task(self._individual_scrap(session, obj, sem))
            tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/all/torrents/{}/{}.html".format(
                quote(query), page
            )
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
                    if page >= 25:
                        break
                    page += 1
                    url = self.BASE_URL + "/all/torrents/{}/{}.html".format(
                        quote(query), page
                    )
                    htmls = await Scraper().get_all_results(session, url)
                    result, urls = self._parser(htmls, idx)
                    if result is None or len(result["data"]) == 0:
                        break
                    seen = {o["url"] for o in results["data"]}
                    for obj in result["data"]:
                        if obj["url"] not in seen:
                            results["data"].append(obj)
                            seen.add(obj["url"])
                    results["current_page"] = page
                    if result.get("total_pages"):
                        results["total_pages"] = result["total_pages"]
                    results["time"] = time.time() - start_time
                    results["total"] = len(results["data"])
                results["data"] = results["data"][0 : self.LIMIT]
                results["total"] = len(results["data"])
                results = await self._get_torrent(results, session)
                results["time"] = time.time() - start_time
                results["total"] = len(results["data"])
            return results
        return result

    async def trending(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL
            return await self.parser_result(start_time, url, session)

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
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
