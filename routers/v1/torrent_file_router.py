import re
from urllib.parse import quote, unquote, urlsplit

import aiohttp
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from constants.headers import HEADER_AIO
from helper.session import get_connector

router = APIRouter(tags=["Torrent File Proxy"])

MAX_SIZE = 25 * 1024 * 1024
TIMEOUT = aiohttp.ClientTimeout(total=20)


def _safe_filename(url):
    name = unquote(urlsplit(url).path.split("/")[-1] or "")
    name = re.sub(r"[^\w.\-]", "_", name)
    return name or "torrent.torrent"


@router.get("/")
@router.get("")
async def proxy_torrent(url: str, name: str = ""):
    """Fetch a .torrent file through this server and stream it back.

    Lets WZML's Direct Link keep working even when the original torrent CDN
    (t0r.space etc.) blocks the requester's IP.
    """
    if not url.lower().startswith(("http://", "https://")):
        return JSONResponse(status_code=400, content={"error": "Invalid URL."})
    try:
        async with aiohttp.ClientSession(
            connector=get_connector(), connector_owner=False, trust_env=True
        ) as session:
            async with session.get(
                url, headers=HEADER_AIO, timeout=TIMEOUT, allow_redirects=True
            ) as res:
                if res.status >= 400:
                    return JSONResponse(
                        status_code=502, content={"error": "Upstream error."}
                    )
                body = await res.content.read()
    except Exception:
        return JSONResponse(
            status_code=502, content={"error": "Failed to fetch torrent."}
        )
    # Reject upstream error pages, but pass through real files of any kind:
    # book sites (Hindi books, archive.org, libgen) put direct PDF/EPUB links
    # in "torrent" so WZML's Direct Link must stream those too, not just
    # bencoded .torrent files.
    head = body[:512].lstrip()
    if len(body) > MAX_SIZE or not body or head.startswith(b"<"):
        return JSONResponse(
            status_code=502, content={"error": "Invalid file."}
        )
    filename = name or _safe_filename(url)
    return Response(
        content=body,
        media_type="application/x-bittorrent",
        headers={
            "Content-Disposition": 'attachment; filename="{}"'.format(filename)
        },
    )
