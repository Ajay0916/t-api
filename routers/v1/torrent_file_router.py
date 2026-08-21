import re
from helper.logging_setup import get_logger
LOGGER = get_logger("tapi.torrent")
from urllib.parse import quote, unquote, urlsplit

import aiohttp
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from constants.headers import HEADER_AIO
from helper.session import get_connector
from helper.short_links import lookup
from torrents.rutracker import fetch_dl_torrent
from torrents.downloadly import Downloadly

router = APIRouter(tags=["Torrent File Proxy"])

# No size cap: the body streams straight through, so large books/audiobooks
# download fully instead of being cut off mid-file. sock_read bounds idle
# connections so a stalled upstream can't hold the request forever.
TIMEOUT = aiohttp.ClientTimeout(total=180, sock_connect=15, sock_read=60)


def _safe_filename(url):
    name = unquote(urlsplit(url).path.split("/")[-1] or "")
    name = re.sub(r"[^\w.\-]", "_", name)
    return name or "download"


def _upstream_filename(cd):
    """Extract the filename the upstream server chose for the file, so the
    proxy can borrow its extension (libgen sends "...libgen.li.pdf")."""
    if not cd:
        return ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return m.group(1).strip().strip('"')
    return ""


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
@router.get("/{slug}")
async def proxy_torrent(
    request: Request,
    url: str = "",
    name: str = "",
    slug: str = "",
    ext: str = "",
):
    """Fetch a .torrent / book file through this server and stream it back.

    Lets WZML's Direct Link keep working even when the original CDN blocks
    the requester's IP. Streams instead of buffering so large book files on
    slow CDNs (libgen/booksdl, archive.org) download reliably.
    """
    # Short-link form: /torrent_file/<token> without url=...&name=... stays
    # open (shared links in the bot are public); the full-URL proxy form
    # is an open proxy too - the API is public by design.
    if not url and slug:
        info = lookup(slug)
        if not info:
            return JSONResponse(
                status_code=404, content={"error": "Link not found."}
            )
        url = info.get("url") or ""
        if not name:
            name = info.get("name") or ""
        if not ext:
            ext = info.get("ext") or ""

    if not url.lower().startswith(("http://", "https://")):
        return JSONResponse(status_code=400, content={"error": "Invalid URL."})

    # RuTracker dl.php is behind Cloudflare and 403s plain fetches; get the
    # real .torrent through FlareSolverr with the search session cookie.
    if "rutracker.org/forum/dl.php" in url.lower():
        fetched = await fetch_dl_torrent(url)
        if fetched is None:
            return JSONResponse(
                status_code=502, content={"error": "Failed to fetch torrent."}
            )
        body, up_name = fetched
        filename = (name or up_name or "rutracker").strip()
        if not re.search(r"\.torrent$", filename, re.I):
            filename = filename.strip() + ".torrent"
        ascii_name = filename.encode("latin-1", "ignore").decode("latin-1") or "download"
        ascii_name = ascii_name.replace('"', "_").replace("\\", "_")
        disposition = 'attachment; filename="{}"'.format(ascii_name)
        if ascii_name != filename:
            disposition += "; filename*=UTF-8''" + quote(filename)
        return Response(
            content=body,
            media_type="application/x-bittorrent",
            headers={"Content-Disposition": disposition},
        )

    # Downloadly post URLs: resolve actual dl*.downloadly.ir file link first
    _is_dl_post = (
        ("downloadly.ir/" in url.lower() or "downloadlynet.ir/" in url.lower())
        and not re.match(r"https?://dl\d*\.", url)
    )
    if _is_dl_post:
        try:
            parts = await Downloadly().resolve_parts(url)
            if parts:
                url = parts[0]["url"]
                if not name:
                    name = parts[0].get("label", "") or "downloadly_download"
        except Exception:
            pass

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

    up_name = _upstream_filename(res.headers.get("Content-Disposition") or "")
    filename = name or up_name or _safe_filename(url)
    if not re.search(r"\.[a-zA-Z0-9]{2,5}$", filename, re.I):
        chosen = ""
        up_ext = up_name.rsplit(".", 1)[-1] if "." in up_name else ""
        if up_ext and re.fullmatch(r"[a-z0-9]{2,5}", up_ext, re.I):
            chosen = up_ext.lower()
        elif ext and re.fullmatch(r"[a-z0-9]{2,8}", ext, re.I):
            chosen = ext.lower()
        else:
            # The slug in the request path carries the extension the bot
            # picked (gutenberg .../xxx.epub), so borrow it when the name
            # has none and upstream sends no Content-Disposition.
            slug_ext = slug.rsplit(".", 1)[-1] if "." in slug else ""
            if (
                slug_ext
                and slug_ext.lower() != "dl"
                and re.fullmatch(r"[a-z0-9]{2,8}", slug_ext, re.I)
            ):
                chosen = slug_ext.lower()
            else:
                m = re.search(
                    r"\b(pdf|epub|mobi|azw3|djvu|fb2|zip|rar|mp3|m4b|torrent)\b",
                    filename,
                    re.I,
                )
                if m:
                    chosen = m.group(1).lower()
        if chosen:
            filename = filename.strip() + "." + chosen

    # Hindi/Tamil/etc. titles can't go into the latin-1 Content-Disposition
    # header; send an ASCII fallback plus RFC 5987 filename* so browsers
    # still show the original name.
    ascii_name = filename.encode("latin-1", "ignore").decode("latin-1") or "download"
    ascii_name = ascii_name.replace('"', "_").replace("\\", "_")
    disposition = 'attachment; filename="{}"'.format(ascii_name)
    if ascii_name != filename:
        disposition += "; filename*=UTF-8''" + quote(filename)

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
        headers={"Content-Disposition": disposition},
    )
