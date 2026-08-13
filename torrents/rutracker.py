import asyncio
import os
import time
from urllib.parse import quote

import aiohttp
from helper.session import get_connector

TORAPI_URL = (os.getenv("TORAPI_URL") or "http://127.0.0.1:8443").rstrip("/")
TORAPI_ENRICH = (os.getenv("TORAPI_ENRICH") or "1").strip().lower() not in ("0", "false", "no")
ENRICH_CAP = 8
_SEARCH_TIMEOUT = aiohttp.ClientTimeout(total=20)
_ENRICH_TIMEOUT = aiohttp.ClientTimeout(total=8)


class RuTracker:
    """Search results via a self-hosted TorAPI instance (Lifailon/TorAPI).

    TorAPI handles RuTracker mirrors and exposes title/id search endpoints.
    The id endpoint is used to enrich the top results with magnet links,
    since the plain title search does not include hashes.
    """

    _name = "RuTracker"

    def __init__(self):
        self.BASE_URL = TORAPI_URL
        self.LIMIT = None
        self.provider = "rutracker"

    @staticmethod
    def _int(value):
        try:
            return int(str(value).replace(",", "").strip() or 0)
        except (TypeError, ValueError):
            return None

    async def _get_json(self, url, timeout):
        async with aiohttp.ClientSession(
            connector=get_connector(), connector_owner=False, trust_env=True
        ) as session:
            async with session.get(url, timeout=timeout) as res:
                return await res.json(content_type=None)

    async def _magnet(self, tid, sem):
        async with sem:
            try:
                data = await self._get_json(
                    f"{self.BASE_URL}/api/search/id/{self.provider}?id={quote(str(tid))}",
                    _ENRICH_TIMEOUT,
                )
            except Exception:
                return None
            if not isinstance(data, list) or not data:
                return None
            item = data[0]
            if not isinstance(item, dict):
                return None
            magnet = str(item.get("Magnet") or "").strip()
            info_hash = str(item.get("Hash") or "").strip()
            if not magnet and not info_hash:
                return None
            return {"hash": info_hash or None, "magnet": magnet or None}

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit or None
        try:
            page = max(int(page or 1) - 1, 0)
        except (TypeError, ValueError):
            page = 0
        url = (
            f"{self.BASE_URL}/api/search/title/{self.provider}"
            f"?query={quote(query)}&page={page}&year=0"
        )
        try:
            data = await self._get_json(url, _SEARCH_TIMEOUT)
        except Exception:
            return None
        if not isinstance(data, list):
            return {
                "data": [],
                "current_page": page + 1,
                "total_pages": 1,
                "time": time.time() - start_time,
                "total": 0,
            }
        raw = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("Name") or "").strip()
            tid = str(item.get("Id") or "").strip()
            if not name or not tid:
                continue
            raw.append((tid, item))
            if self.LIMIT and len(raw) >= self.LIMIT:
                break
        extras = []
        if raw and TORAPI_ENRICH:
            sem = asyncio.Semaphore(4)
            enrich_n = min(len(raw), ENRICH_CAP)
            extras = await asyncio.gather(
                *(self._magnet(tid, sem) for tid, _ in raw[:enrich_n]),
                return_exceptions=True,
            )
        results = []
        for idx, (tid, item) in enumerate(raw):
            extra = (
                extras[idx]
                if idx < len(extras) and isinstance(extras[idx], dict)
                else None
            )
            results.append(
                {
                    "name": str(item.get("Name") or "").strip(),
                    "size": str(item.get("Size") or "").strip(),
                    "date": str(item.get("Date") or "").strip(),
                    "seeders": self._int(item.get("Seeds")),
                    "leechers": self._int(item.get("Peers")),
                    "uploader": "",
                    "category": str(
                        item.get("Category") or item.get("Type") or ""
                    ).strip(),
                    "url": item.get("Url") or None,
                    "torrent": item.get("Torrent") or None,
                    "hash": (extra or {}).get("hash"),
                    "magnet": (extra or {}).get("magnet"),
                }
            )
        return {
            "data": results,
            "current_page": page + 1,
            "total_pages": 1,
            "time": time.time() - start_time,
            "total": len(results),
        }
