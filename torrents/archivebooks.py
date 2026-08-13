import asyncio
import json
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector

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
        general_q = "mediatype:(texts) AND (title:({}) OR description:({}))".format(
            quote(query), quote(query)
        )
        # Run both queries in parallel: the Hindi query usually matches, and
        # keeping the general fallback alongside avoids a second slow wait
        # on archive.org when it doesn't.
        urls = [
            self.BASE_URL
            + (
                "/advancedsearch.php?q={}&fl[]=identifier&fl[]=title"
                "&fl[]=downloads&fl[]=date&rows={}&output=json&sort[]=downloads+desc"
            ).format(quote(q), limit)
            for q in (hindi_q, general_q)
        ]
        htmls = await asyncio.gather(
            *(Scraper().get_all_results(session, u) for u in urls)
        )
        docs = self._parse_docs(htmls[0])
        if docs:
            return docs
        return self._parse_docs(htmls[1])

    @staticmethod
    def _parse_docs(html):
        try:
            data = json.loads(html[0])
            return data.get("response", {}).get("docs", []) or []
        except Exception:
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
                obj["extension"] = f["name"].rsplit(".", 1)[-1].lower()
                obj["torrent"] = self.BASE_URL + "/download/{}/{}".format(
                    identifier, quote(f["name"])
                )
                size = f.get("size")
                if size:
                    obj["size"] = self._format_size(int(size))
                obj["url"] = self.BASE_URL + "/details/" + identifier
            except Exception:
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
                    session, item["identifier"], item, sem
                )
            )
            tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False, trust_env=True) as session:
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
