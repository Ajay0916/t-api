import asyncio
import hashlib
import json
import re
import time
from urllib.parse import quote as requests_quote
import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import EXTO
from constants.headers import HEADER_AIO, AIO_TIMEOUT
from helper.trackers import build_torrent_url

HOSTS = [EXTO, "https://extratorrent.st"]


class ExtraTorrent:
    _name = "ext"

    def __init__(self):
        self.BASE_URL = EXTO
        self.LIMIT = None

    async def _fetch_page(self, session, path):
        start = HOSTS.index(self.BASE_URL) if self.BASE_URL in HOSTS else 0
        for i in range(len(HOSTS)):
            host = HOSTS[(start + i) % len(HOSTS)]
            try:
                htmls = await Scraper().get_all_results(session, host + path)
                if htmls and htmls[0]:
                    self.BASE_URL = host
                    return htmls
            except Exception:
                continue
        return None

    @staticmethod
    def _clean(td, prefix):
        return td.get_text(strip=True).replace(prefix, "").strip()

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                my_dict = {"data": []}
                table = soup.find("table", class_="search-table")
                if table is None:
                    if "nothing-found" in html or "No results" in html:
                        return {"data": [], "current_page": 1, "total_pages": 1}
                    continue
                for tr in table.find_all("tr"):
                    td = tr.find_all("td")
                    if len(td) != 7:
                        continue
                    link = td[0].find("a", href=True)
                    if link is None:
                        continue
                    name = link.get_text(strip=True)
                    if not name:
                        continue
                    href = link["href"]
                    if not href.startswith("http"):
                        href = self.BASE_URL + href
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": self._clean(td[1], "Size"),
                            "date": self._clean(td[3], "Age"),
                            "seeders": self._clean(td[4], "Seeds"),
                            "leechers": self._clean(td[5], "Leechs"),
                            "url": href,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                current_page = 1
                total_pages = 1
                active = soup.select_one("ul.pages li.active")
                if active:
                    try:
                        current_page = int(active.get_text(strip=True))
                    except:
                        ...
                pages = []
                for a in soup.select("ul.pages a[href]"):
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

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                async with session.get(url, headers=HEADER_AIO, timeout=AIO_TIMEOUT) as res:
                    html = await res.text()
                tid_match = re.search(r"-(\d+)/?$", url)
                if not tid_match:
                    tid_match = re.search(r'data-id="(\d+)"', html)
                page_token = re.search(r"window\.pageToken\s*=\s*'([^']+)'", html)
                csrf = re.search(r"window\.csrfToken\s*=\s*'([^']+)'", html)
                if not (tid_match and page_token and csrf):
                    return
                timestamp = int(time.time())
                hmac = hashlib.sha256(
                    "{}|{}|{}".format(
                        tid_match.group(1), timestamp, page_token.group(1)
                    ).encode()
                ).hexdigest()
                data = {
                    "torrent_id": tid_match.group(1),
                    "download_type": "magnet",
                    "timestamp": timestamp,
                    "hmac": hmac,
                    "sessid": csrf.group(1),
                }
                headers = {
                    "User-Agent": HEADER_AIO["User-Agent"],
                    "Referer": url,
                    "X-Requested-With": "XMLHttpRequest",
                }
                async with session.post(
                    self.BASE_URL + "/ajax/getTorrentMagnet.php",
                    data=data,
                    headers=headers,
                ) as res:
                    body = await res.text()
                resp = json.loads(body)
                if resp.get("success") and resp.get("url"):
                    magnet = resp["url"]
                    obj["magnet"] = magnet
                    hash_match = re.search(r"([a-fA-F0-9]{32,40})\b", magnet)
                    if hash_match:
                        obj["hash"] = hash_match.group(1)
                        obj["torrent"] = build_torrent_url(
                            hash_match.group(1), obj.get("name") or ""
                        )
            except:
                return None

    async def _get_torrent(self, result, session, urls):
        tasks = []
        sem = asyncio.Semaphore(20)
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(
                            session, url, result["data"][idx], sem
                        )
                    )
                    tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    async def parser_result(self, start_time, path, session):
        htmls = await self._fetch_page(session, path)
        if htmls is None:
            return None
        results = self._parser(htmls)
        if results is not None:
            urls = [item["url"] for item in results["data"]]
            results = await self._get_torrent(results, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            return results
        return results

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            path = "/browse/?q={}".format(requests_quote(query))
            if page > 1:
                path += "&page={}".format(page)
            results = await self.parser_result(start_time, path, session)
            if results is None:
                return None
            results["current_page"] = page
            while len(results["data"]) < self.LIMIT:
                try:
                    total_pages = results.get("total_pages", page)
                except:
                    break
                if page >= total_pages or page >= 25:
                    break
                page += 1
                path = "/browse/?q={}&page={}".format(requests_quote(query), page)
                res = await self.parser_result(
                    time.time() - start_time, path, session
                )
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
