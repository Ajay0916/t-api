import asyncio
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from curl_cffi.const import CurlOpt
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from constants.base_url import MAGNETDL

HOSTS = [MAGNETDL]
from helper.trackers import build_magnet, build_torrent_url
from helper.plain_curl import fetch_jina, fetch_plain


class Magnetdl:
    _name = "MagnetDL"

    def __init__(self):
        self.BASE_URL = MAGNETDL
        self.LIMIT = None

    async def _fetch(self, session, url):
        # curl_cffi with Chrome impersonation bypasses most anti-bot measures
        # and is the fastest path. Plain curl and jina are fallbacks.
        try:
            r = await session.get(url, timeout=10)
            if r.status_code < 400 and r.text and len(r.text) > 500:
                return r.text
        except Exception:
            pass
        html = await fetch_plain(url, timeout=10)
        if html:
            return html
        return await fetch_jina(url, timeout=12)

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                my_dict = {"data": []}
                for tr in soup.find_all("tr"):
                    td = tr.find_all("td")
                    if len(td) != 7:
                        continue
                    name = td[1].get_text(strip=True)
                    link = td[1].find("a", href=True)
                    if not name or not link:
                        continue
                    href = link["href"]
                    if href.startswith(("http://", "https://")):
                        # Real result links are same-site absolute URLs now;
                        # SEO-spam rows link to external pages, so only
                        # on-site links pass.
                        if "magnetdl" not in href:
                            continue
                    else:
                        href = self.BASE_URL + href
                    my_dict["data"].append(
                        {
                            "name": name,
                            "size": td[4].get_text(strip=True),
                            "date": td[2].get_text(strip=True),
                            "category": td[3].get_text(strip=True),
                            "seeders": td[5].get_text(strip=True),
                            "leechers": td[6].get_text(strip=True),
                            "url": href,
                            "hash": None,
                            "magnet": None,
                            "torrent": None,
                        }
                    )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                return my_dict
        except Exception:
            return None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                html = await self._fetch(session, url)
                if not html:
                    return
                soup = BeautifulSoup(html, "html.parser")
                dt = soup.find("dt", string=re.compile(r"Info Hash", re.I))
                info_hash = None
                if dt:
                    dd = dt.find_next_sibling("dd")
                    info_hash = dd.get_text(strip=True) if dd else None
                if not info_hash:
                    # jina's proxy HTML keeps the raw 40-hex info hash even
                    # though the dt/dd structure is rewritten.
                    m = re.search(r"[0-9a-fA-F]{40}", html)
                    info_hash = m.group(0) if m else None
                if info_hash:
                    obj["hash"] = info_hash
                    obj["magnet"] = build_magnet(info_hash, obj["name"])
                    obj["torrent"] = build_torrent_url(info_hash, obj["name"])
            except Exception:
                return None

    async def _get_torrent(self, result, session, urls):
        tasks = []
        sem = asyncio.Semaphore(4)
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(session, url, obj, sem)
                    )
                    tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    async def parser_result(self, start_time, url, session, page=1, query=None):
        html = await self._fetch(session, url)
        results = self._parser([html]) if html else None
        if results is not None:
            urls = [item["url"] for item in results["data"]]
            results = await self._get_torrent(results, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            if query is not None:
                results["current_page"] = page
                while len(results["data"]) < self.LIMIT:
                    page += 1
                    url = self.BASE_URL + "/search/?q={}&page={}".format(
                        quote(query), page
                    )
                    html = await self._fetch(session, url)
                    res = self._parser([html]) if html else None
                    if res is None or len(res["data"]) == 0:
                        break
                    urls = [item["url"] for item in res["data"]]
                    res = await self._get_torrent(res, session, urls)
                    for obj in res["data"]:
                        results["data"].append(obj)
                    results["current_page"] = page
                    results["time"] = time.time() - start_time
                    results["total"] = len(results["data"])
                    if len(res["data"]) < 10 or page >= 25:
                        break
                results["data"] = results["data"][0 : self.LIMIT]
                results["total"] = len(results["data"])
            return results
        return results

    async def search(self, query, page, limit):
        async with AsyncSession(
            impersonate="chrome",
            curl_options={CurlOpt.IPRESOLVE: 1},
        ) as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/search/?q={}&page={}".format(
                quote(query), page
            )
            result = await self.parser_result(
                start_time, url, session, page=page, query=query
            )
            if result and result.get("data"):
                return result
            for host in HOSTS:
                if host == self.BASE_URL:
                    continue
                try:
                    self.BASE_URL = host
                    url = self.BASE_URL + "/search/?q={}&page={}".format(
                        quote(query), page
                    )
                    result = await self.parser_result(
                        time.time(), url, session, page=page, query=query
                    )
                    if result and result.get("data"):
                        return result
                except Exception:
                    continue
            self.BASE_URL = MAGNETDL
            return result

    async def recent(self, category, page, limit):
        async with AsyncSession(
            impersonate="chrome",
            curl_options={CurlOpt.IPRESOLVE: 1},
        ) as session:
            start_time = time.time()
            self.LIMIT = limit
            if not category:
                url = self.BASE_URL + "/download/movies/"
            else:
                if category == "books":
                    category = "e-books"
                elif category == "apps":
                    category = "software"
                url = self.BASE_URL + "/download/{}/".format(category)
            return await self.parser_result(start_time, url, session)
