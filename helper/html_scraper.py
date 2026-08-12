import os
import asyncio
import aiohttp
from .asyncioPoliciesFix import decorator_asyncio_fix
from constants.headers import HEADER_AIO, AIO_TIMEOUT

HTTP_PROXY = os.environ.get("HTTP_PROXY", None)


class Scraper:
    @decorator_asyncio_fix
    async def _get_html(self, session, url, retries=2):
        for attempt in range(retries):
            try:
                async with session.get(
                    url,
                    headers=HEADER_AIO,
                    timeout=AIO_TIMEOUT,
                    proxy=HTTP_PROXY,
                ) as r:
                    if r.status >= 400:
                        return None
                    return await r.text()
            except Exception:
                if attempt == retries - 1:
                    return None
                await asyncio.sleep(1)
        return None

    async def get_all_results(self, session, url):
        return await asyncio.gather(asyncio.create_task(self._get_html(session, url)))
