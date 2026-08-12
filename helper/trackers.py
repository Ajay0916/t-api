import asyncio
from urllib.parse import quote

import aiohttp

from constants.headers import AIO_TIMEOUT
from helper.session import get_connector

STATIC_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://9.rarbg.to:2710/announce",
    "udp://tracker.leechers-paradise.org:6969/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.qu.ax:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "http://tracker.opentrackr.org:1337/announce",
    "http://tracker.openbittorrent.com:80/announce",
]

TORRENT_CDN = "https://itorrents.net/torrent/{}.torrent"

TRACKERS_URL = (
    "https://raw.githubusercontent.com/ngosang/trackerslist/master/"
    "trackers_best.txt"
)

_live_trackers = None
_refresh_started = False


async def _refresh():
    """Fetch the live ngosang best-trackers list once per process."""
    global _live_trackers
    try:
        async with aiohttp.ClientSession(
            connector=get_connector(), connector_owner=False
        ) as session:
            async with session.get(TRACKERS_URL, timeout=AIO_TIMEOUT) as res:
                if res.status >= 400:
                    return
                text = await res.text()
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if lines:
            _live_trackers = lines
    except Exception:
        pass


def _ensure_refresh():
    """Schedule the tracker refresh once, without blocking the caller."""
    global _refresh_started
    if _refresh_started or _live_trackers is not None:
        return
    _refresh_started = True
    try:
        asyncio.get_running_loop().create_task(_refresh())
    except RuntimeError:
        pass


def get_trackers():
    """Return the freshest tracker list available (static fallback)."""
    _ensure_refresh()
    if not _live_trackers:
        return STATIC_TRACKERS
    seen = set(_live_trackers)
    return _live_trackers + [t for t in STATIC_TRACKERS if t not in seen]


def build_magnet(info_hash, name):
    trackers = get_trackers()
    dn = quote(name)
    tr = "".join("&tr={}".format(quote(t)) for t in trackers)
    return "magnet:?xt=urn:btih:{}&dn={}{}".format(info_hash, dn, tr)


def build_torrent_url(info_hash, name):
    """Build a .torrent download link from an infohash via itorrents.net."""
    return TORRENT_CDN.format(info_hash) + "?title=" + quote(name)
