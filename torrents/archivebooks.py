import asyncio
import json
import time
from urllib.parse import quote

import aiohttp

from constants.base_url import ARCHIVEBOOKS
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper


class ArchiveBooks:
    _name = "Archive Books"

    def __init__(self):
        self.BASE_URL = ARCHIVEBOOKS
        self.LIMIT = None

    async def _search_items(self, session, query, limit):
        hindi_q = (
            "language:(Hindi) AND mediatype:(texts) AND "
            "(title:({}) OR description:({}))"
        ).format(quote(query), quote(query))
        url = self.BASE_URL + (
            "/advancedsearch.php?q={}&fl[]=identifier&fl[]=title"
            "&fl[]=downloads&fl[]=date&rows={}&output=json&sort[]=downloads+desc"
        ).format(quote(hindi_q), limit)
        html = await Scraper().get_all_results(session, url)
        docs = self._parse_docs(html)
        if docs:
            return docs
        general_q = "mediatype:(texts) AND (title:({}) OR description:({}))".format(
            quote(query), quote(query)
        )
        url = self.BASE_URL + (
            "/advancedsearch.php?q={}&fl[]=identifier&fl[]=title"
            "&fl[]=downloads&fl[]=date&rows={}&output=json&sort[]=downloads+desc"
        ).format(quote(general_q), limit)
        html = await Scraper().get_all_results(session, url)
        return self._parse_docs(html)

    @staticmethod
    def _parse_docs(html):
        try:
            data = json.loads(html[0])
            return data.get("response", {}).get("docs", []) or []
        except:
            return []

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, identifier, obj, sem):
        async with sem:
            try:
                url = self.BASE_URL + "/metadata/" + identifier
                html = await Scraper().get_all_results(session, url)
                if not html or not html[0]:
                    return None
                data = json.loads(html[0])
                files = data.get("files", [])
                books = [
                    f
                    for f in files
                    if f.get("name", "").lower().endswith(
                        (".pdf", ".epub", ".djvu", ".azw3", ".mobi", ".fb2")
                    )
                ]
                if not books:
                    return None
                books.sort(
                    key=lambda f: int(f.get("size") or 0), reverse=True
                )
                f = books[0]
                obj["torrent"] = self.BASE_URL + "/download/{}/{}".format(
                    identifier, quote(f["name"])
                )
                size = f.get("size")
                if size:
                    obj["size"] = self._format_size(int(size))
                obj["url"] = self.BASE_URL + "/details/" + identifier
            except:
                return None

    @staticmethod
    def _format_size(num):
        if num >= 1024 ** 3:
            return "{:.2f} GB".format(num / 1024 ** 3)
        if num >= 1024 ** 2:
            return "{:.1f} MB".format(num / 1024 ** 2)
        return "{} KB".format(int(num / 1024))

    async def _get_links(self, result, session):
        tasks = []
        sem = asyncio.Semaphore(6)
        for idx, item in enumerate(result["data"]):
            task = asyncio.create_task(
                self._individual_scrap(
                    session, item["identifier"], result["data"][idx], sem
                )
            )
            tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            docs = await self._search_items(session, query, limit)
            if not docs:
                return None
            results = {"data": []}
            for d in docs:
                title = (d.get("title") or "").strip()
                if not title or len(title) < 5:
                    continue
                if title.lower().startswith("none"):
                    continue
                results["data"].append(
                    {
                        "name": title,
                        "identifier": d.get("identifier"),
                        "date": d.get("date"),
                    }
                )
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            results = await self._get_links(results, session)
            results["data"] = [
                d for d in results["data"] if d.get("torrent")
            ]
            results["total"] = len(results["data"])
            return results
