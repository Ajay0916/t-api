import asyncio
import re
import time
from urllib.parse import quote

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from curl_cffi.const import CurlOpt
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from constants.base_url import FREECOURSEWEB
from helper.trackers import build_torrent_url
from helper.plain_curl import fetch_jina, fetch_plain


class FreeCourseWeb:
    _name = "Free Course Web"

    def __init__(self):
        self.BASE_URL = FREECOURSEWEB
        self.LIMIT = None

    async def _fetch(self, session, url):
        # Cloudflare intermittently blackholes this host's direct requests
        # (curl included, TCP 000) while serving other IPs, so the chain is:
        # system curl -> curl_cffi -> r.jina.ai proxy (same HTML back). Each
        # leg is timeboxed to stay inside the router's 40s per-site deadline.
        html = await fetch_plain(url, timeout=6)
        if html:
            return html
        try:
            r = await session.get(url, timeout=8)
            if r.status_code < 400:
                return r.text
        except Exception:
            pass
        return await fetch_jina(url, timeout=12)
        return None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                html = await self._fetch(session, url)
                if not html:
                    return None
                m = re.search(r'href="(magnet:\?xt=[^"]+)"', html)
                if not m:
                    return None
                magnet = m.group(1)
                obj["magnet"] = magnet
                hm = re.search(r"([{a-f\d,A-F\d}]{32,40})\b", magnet)
                if hm:
                    obj["hash"] = hm.group(0)
                    obj["torrent"] = build_torrent_url(hm.group(0), obj.get("name") or "")
            except Exception:
                return None

    async def _get_magnets(self, result, session, urls):
        tasks = []
        sem = asyncio.Semaphore(6)
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(session, url, obj, sem)
                    )
                    tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                my_dict = {"data": []}
                for a in soup.select("h2.entry-title.post-title a[href]"):
                    name = a.get_text(" ", strip=True)
                    url = a["href"]
                    if url.startswith("/"):
                        url = self.BASE_URL + url
                    my_dict["data"].append({"name": name, "url": url})
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    page_nums = []
                    for a in soup.select('a[href*="/page/"]'):
                        m = re.search(r"/page/(\d+)/", a["href"])
                        if m:
                            page_nums.append(int(m.group(1)))
                    if page_nums:
                        my_dict["total_pages"] = max(page_nums)
                except Exception:
                    ...
                return my_dict
        except Exception:
            return None

    async def search(self, query, page, limit):
        async with AsyncSession(
            impersonate="chrome",
            curl_options={CurlOpt.IPRESOLVE: 1},
        ) as session:
            start_time = time.time()
            self.LIMIT = limit
            return await self._collect(
                session,
                lambda p: (
                    self.BASE_URL + "/page/{}/?s={}".format(p, quote(query))
                    if p > 1
                    else self.BASE_URL + "/?s={}".format(quote(query))
                ),
                page,
                start_time,
            )

    async def recent(self, category, page, limit):
        async with AsyncSession(
            impersonate="chrome",
            curl_options={CurlOpt.IPRESOLVE: 1},
        ) as session:
            start_time = time.time()
            self.LIMIT = limit
            return await self._collect(
                session,
                lambda p: (
                    self.BASE_URL + "/tutorialsv4/page/{}/".format(p)
                    if p > 1
                    else self.BASE_URL + "/tutorialsv4/"
                ),
                page,
                start_time,
            )

    async def _collect(self, session, url_fn, page, start_time):
        all_data = []
        total_pages = page
        current = page
        while True:
            html = await self._fetch(session, url_fn(current))
            results = self._parser([html]) if html else None
            if results is None or len(results["data"]) == 0:
                break
            seen = {obj["url"] for obj in all_data}
            for obj in results["data"]:
                if obj["url"] not in seen:
                    all_data.append(obj)
            if results.get("total_pages"):
                total_pages = results["total_pages"]
            if len(all_data) >= self.LIMIT:
                break
            if current >= total_pages or current >= 25:
                break
            current += 1
        if not all_data:
            return None
        urls = [obj["url"] for obj in all_data]
        results = {"data": all_data}
        results = await self._get_magnets(results, session, urls)
        results["data"] = results["data"][0 : self.LIMIT]
        results["time"] = time.time() - start_time
        results["total"] = len(results["data"])
        results["current_page"] = page
        results["total_pages"] = total_pages
        return results
