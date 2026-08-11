import asyncio
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import LIBGEN
from constants.headers import HEADER_AIO, AIO_TIMEOUT


class Libgen:
    _name = "Libgen"
    def __init__(self):
        self.BASE_URL = LIBGEN
        self.LIMIT = None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                async with session.get(url, headers=HEADER_AIO, timeout=AIO_TIMEOUT) as res:
                    html = await res.text(encoding="ISO-8859-1")
                    soup = BeautifulSoup(html, "html.parser")
                    try:
                        for a in soup.find_all("a", href=True):
                            if a.get_text(strip=True) == "One-filetorrent":
                                if a["href"] != "#":
                                    obj["torrent"] = self.BASE_URL + a["href"]
                                break
                        if not obj.get("torrent"):
                            md5a = soup.find("a", href=lambda h: h and "get.php" in h)
                            if md5a:
                                href = md5a["href"]
                                if href.startswith("/"):
                                    href = self.BASE_URL + href
                                obj["torrent"] = href
                        poster = soup.find("img")
                        if poster and poster.get("src", "").startswith("/"):
                            obj["poster"] = self.BASE_URL + poster["src"]
                        elif poster:
                            obj["poster"] = poster["src"]
                    except Exception:
                        ...
            except:
                return None

    async def _get_torrent(self, result, session, urls):
        tasks = []
        sem = asyncio.Semaphore(3)
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(session, url, result["data"][idx], sem)
                    )
                    tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                list_of_urls = []
                my_dict = {"data": []}
                for tr in soup.find_all("tr"):
                    td = tr.find_all("td")
                    if len(td) < 9:
                        continue
                    name_link = td[0].find("a", href=True)
                    if not name_link:
                        continue
                    name = td[0].get_text(" ", strip=True)
                    edition = td[0].find("a", href=lambda h: h and "edition.php" in h)
                    file_link = td[0].find("a", href=lambda h: h and "file.php" in h)
                    href = (
                        edition["href"]
                        if edition
                        else file_link["href"]
                        if file_link
                        else name_link["href"]
                    )
                    url = self.BASE_URL + "/" + href
                    list_of_urls.append(url)
                    authors = [a.text.strip() for a in td[1].find_all("a")]
                    if not authors and td[1].get_text(strip=True):
                        authors = [td[1].get_text(strip=True)]
                    md5a = td[8].find("a", href=lambda h: h and "get.php" in h)
                    download = self.BASE_URL + md5a["href"] if md5a else None
                    md5 = md5a["href"].split("md5=")[-1] if md5a else None
                    my_dict["data"].append(
                        {
                            "id": md5,
                            "hash": md5,
                            "magnet": None,
                            "torrent": download,
                            "authors": authors,
                            "name": name,
                            "publisher": td[2].get_text(strip=True),
                            "year": td[3].get_text(strip=True),
                            "pages": td[5].get_text(strip=True),
                            "language": td[4].get_text(strip=True),
                            "size": td[6].get_text(strip=True),
                            "extension": td[7].get_text(strip=True),
                            "download": download,
                            "url": url,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                return my_dict, list_of_urls
        except:
            return None, None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/index.php?req={}&res=100".format(
                quote(query)
            )
            return await self.parser_result(start_time, url, session)

    async def parser_result(self, start_time, url, session):
        htmls = await Scraper().get_all_results(session, url)
        result, urls = self._parser(htmls)
        if result is not None:
            results = await self._get_torrent(result, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results
        return result
