import asyncio
import json
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector

from constants.base_url import HINDIAUDIO
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.author_utils import clean_archive_creators
from helper.html_scraper import Scraper


class HindiAudio:
    _name = "Hindi Audio Books & Media"

    def __init__(self):
        self.BASE_URL = HINDIAUDIO
        self.LIMIT = None

    async def _search_items(self, session, query, limit, page=1):
        hindi_q = (
            "language:(Hindi) AND (mediatype:(audio) OR mediatype:(texts)) AND "
            "(title:({}) OR description:({}))"
        ).format(quote(query), quote(query))
        general_q = (
            "(mediatype:(audio) OR mediatype:(texts)) AND "
            "(title:({}) OR description:({}))"
        ).format(quote(query), quote(query))
        # Run both queries in parallel: the Hindi query usually matches, and
        # keeping the general fallback alongside avoids a second slow wait
        # on archive.org when it doesn't.
        urls = [
            self.BASE_URL
            + (
                "/advancedsearch.php?q={}&fl[]=identifier&fl[]=title"
                "&fl[]=downloads&fl[]=date&fl[]=mediatype&rows={}&page={}"
                "&output=json&sort[]=downloads+desc"
            ).format(quote(q), limit, max(int(page or 1), 1))
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
                authors = clean_archive_creators(
                    (data.get("metadata") or {}).get("creator")
                )
                if authors:
                    obj["authors"] = authors
                files = data.get("files", [])
                audio = [
                    f
                    for f in files
                    if f.get("name", "").lower().endswith(
                        (".mp3", ".m4a", ".ogg", ".opus", ".flac", ".wav")
                    )
                ]
                texts = [
                    f
                    for f in files
                    if f.get("name", "").lower().endswith(
                        (".pdf", ".epub", ".djvu", ".azw3", ".mobi")
                    )
                ]
                pool = audio if audio else texts
                if not pool:
                    return None
                pool.sort(
                    key=lambda f: int(f.get("size") or 0), reverse=True
                )
                f = pool[0]
                name = f["name"]
                obj["extension"] = name.rsplit(".", 1)[-1].lower()
                obj["torrent"] = self.BASE_URL + "/download/{}/{}".format(
                    identifier, quote(name)
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
            docs = await self._search_items(session, query, limit, page)
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
                        "category": "Audiobook",
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
