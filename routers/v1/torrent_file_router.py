import re
from urllib.parse import quote, unquote, urlsplit

import aiohttp
from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from constants.headers import HEADER_AIO
from helper.session import get_connector

router = APIRouter(tags=["Torrent File Proxy"])

# No size cap: the body streams straight through, so large books/audiobooks
# download fully instead of being cut off mid-file. sock_read bounds idle
# connections so a stalled upstream can't hold the request forever.
TIMEOUT = aiohttp.ClientTimeout(total=180, sock_connect=15, sock_read=60)


def _safe_filename(url):
    name = unquote(urlsplit(url).path.split("/")[-1] or "")
    name = re.sub(r"[^\w.\-]", "_", name)
    return name or "download"


def _media_type(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "torrent": "application/x-bittorrent",
        "pdf": "application/pdf",
        "epub": "application/epub+zip",
        "mobi": "application/x-mobipocket-ebook",
        "azw3": "application/vnd.amazon.ebook",
        "zip": "application/zip",
        "rar": "application/vnd.rar",
        "7z": "application/x-7z-compressed",
        "mp3": "audio/mpeg",
        "m4b": "audio/mp4",
    }.get(ext, "application/octet-stream")


@router.get("/")
@router.get("")
async def proxy_torrent(url: str, name: str = ""):
    """Fetch a .torrent / book file through this server and stream it back.

    Lets WZML's Direct Link keep working even when the original CDN blocks
    the requester's IP. Streams instead of buffering so large book files on
    slow CDNs (libgen/booksdl, archive.org) download reliably.
    """
    if not url.lower().startswith(("http://", "https://")):
        return JSONResponse(status_code=400, content={"error": "Invalid URL."})
    try:
        session = aiohttp.ClientSession(
            connector=get_connector(), connector_owner=False, trust_env=True
        )
        res = await session.get(
            url, headers=HEADER_AIO, timeout=TIMEOUT, allow_redirects=True
        )
    except Exception:
        try:
            await session.close()
        except Exception:
            pass
        return JSONResponse(
            status_code=502, content={"error": "Failed to fetch file."}
        )
    if res.status >= 400:
        await res.release()
        await session.close()
        return JSONResponse(
            status_code=502, content={"error": "Upstream error."}
        )
    # Peek at the start of the body: upstream error pages are HTML and must
    # be rejected, but real files of any kind (torrent/pdf/epub/zip) pass.
    try:
        head = await res.content.read(512)
    except Exception:
        head = b""
    if not head or head.lstrip().startswith(b"<"):
        await res.release()
        await session.close()
        return JSONResponse(status_code=502, content={"error": "Invalid file."})

    filename = name or _safe_filename(url)

    async def _stream():
        try:
            yield head
            async for chunk in res.content.iter_chunked(64 * 1024):
                yield chunk
        finally:
            await res.release()
            await session.close()

    return StreamingResponse(
        _stream(),
        media_type=_media_type(filename),
        headers={
            "Content-Disposition": 'attachment; filename="{}"'.format(filename)
        },
    )
