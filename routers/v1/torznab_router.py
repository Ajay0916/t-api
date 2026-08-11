import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

from fastapi import APIRouter, HTTPException, Response

from routers.v1.combo_routers import get_search_combo

router = APIRouter(tags=["Torznab"])

API_KEY = os.environ.get("PYTORRENT_API_KEY")
TORZNAB_NS = "http://torznab.com/schemas/2015/feed"
ATOM_NS = "http://www.w3.org/2005/Atom"
register_namespace("torznab", TORZNAB_NS)
register_namespace("atom", ATOM_NS)

CAT_MAP = {
    "movies": "2000",
    "movie": "2000",
    "tv": "5000",
    "television": "5000",
    "series": "5000",
    "anime": "5050",
    "audio": "3000",
    "music": "3000",
    "audiobook": "3030",
    "books": "7000",
    "ebooks": "7000",
    "books/technical": "7050",
    "games": "4000",
    "pc": "4000",
    "software": "4000",
    "applications": "4000",
    "other": "8000",
}


def _torznab_cat(category):
    key = re.sub(r"[^a-z0-9/]+", " ", (category or "").strip().lower())
    key = re.sub(r"\s+", " ", key).strip()
    if not key:
        return None
    if key in CAT_MAP:
        return CAT_MAP[key]
    if key.startswith("movies") or "movie" in key:
        return "2000"
    if "anime" in key:
        return "5050"
    if "tv" in key or "television" in key or "series" in key or "episode" in key:
        return "5000"
    if "audio" in key or "music" in key:
        return "3000"
    if "book" in key or "ebook" in key or "magazine" in key:
        return "7000"
    if "game" in key or "software" in key or "app" in key:
        return "4000"
    return None


def _rfc1123(date_str):
    try:
        dt = parsedate_to_datetime(str(date_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    except (TypeError, ValueError, OverflowError):
        return None


def _caps_xml():
    caps = Element("caps")
    server = SubElement(caps, "server")
    server.set("title", "Torrents API")
    server.set("version", "1.0")
    limits = SubElement(caps, "limits")
    limits.set("max", "100")
    limits.set("default", "50")
    searching = SubElement(caps, "searching")
    for name, params in (
        ("search", "q"),
        ("tv-search", "q,season,ep,imdbid"),
        ("movie-search", "q,imdbid"),
    ):
        node = SubElement(searching, name)
        node.set("available", "yes")
        node.set("supportedParams", params)
    categories = SubElement(caps, "categories")
    for cat_id, name, subs in (
        ("2000", "Movies", (("2010", "Movies/BluRay"), ("2030", "Movies/HD"), ("2050", "Movies/SD"))),
        ("3000", "Audio", (("3030", "Audio/Audiobook"),)),
        ("4000", "PC", ()),
        ("5000", "TV", (("5050", "TV/Anime"), ("5060", "TV/Documentary"))),
        ("7000", "Books", (("7010", "Books/Ebooks"), ("7050", "Books/Technical"))),
        ("8000", "Other", ()),
    ):
        cat = SubElement(categories, "category")
        cat.set("id", cat_id)
        cat.set("name", name)
        for sub_id, sub_name in subs:
            sub = SubElement(cat, "subcat")
            sub.set("id", sub_id)
            sub.set("name", sub_name)
    return caps


def _feed_xml(results, q, offset, limit):
    rss = Element("rss")
    rss.set("version", "2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "Torrents API"
    SubElement(channel, "description").text = "Unofficial torrents / books / courses API"
    SubElement(channel, "link").text = "https://github.com/Ajay0916/t-api"
    SubElement(channel, "language").text = "en-us"
    for item in results[offset : offset + limit]:
        name = item.get("name") or "Untitled"
        magnet = item.get("magnet")
        torrent = item.get("torrent")
        link = magnet or torrent or (item.get("url") or "")
        infohash = item.get("hash")
        guid = infohash or link or name
        node = SubElement(channel, "item")
        SubElement(node, "title").text = name
        g = SubElement(node, "guid")
        g.set("isPermaLink", "false")
        g.text = str(guid)
        SubElement(node, "link").text = link
        pub = _rfc1123(item.get("date"))
        if pub:
            SubElement(node, "pubDate").text = pub
        size = item.get("size_bytes") or 0
        SubElement(node, "size").text = str(size)
        cat = _torznab_cat(item.get("category"))
        attrs = [
            ("category", cat or "8000"),
            ("seeders", str(item.get("seeders") or 0)),
            ("peers", str((item.get("seeders") or 0) + (item.get("leechers") or 0))),
        ]
        if infohash:
            attrs.append(("infohash", str(infohash)))
        if magnet:
            attrs.append(("magneturl", str(magnet)))
        if size:
            attrs.append(("size", str(size)))
        for name_attr, value in attrs:
            a = SubElement(node, f"{{{TORZNAB_NS}}}attr")
            a.set("name", name_attr)
            a.set("value", value)
    return tostring(rss, encoding="unicode", xml_declaration=True)


@router.get("")
async def torznab(
    t: str = "search",
    q: Optional[str] = "",
    cat: Optional[str] = "",
    limit: Optional[int] = 50,
    offset: Optional[int] = 0,
    minseeders: Optional[int] = 0,
    imdbid: Optional[str] = "",
    season: Optional[int] = None,
    ep: Optional[int] = None,
    apikey: Optional[str] = "",
):
    if API_KEY and apikey != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if t == "caps":
        return Response(
            tostring(_caps_xml(), encoding="unicode", xml_declaration=True),
            media_type="application/xml",
        )
    if t not in ("search", "tvsearch", "movie"):
        raise HTTPException(status_code=400, detail="Unsupported operation")
    limit = max(0, min(limit or 50, 100))
    offset = max(0, offset or 0)
    query = (q or "").strip()
    if imdbid:
        query = (query + " " + imdbid).strip()
    if not query:
        return Response(_feed_xml([], q, offset, limit), media_type="application/xml")
    resp = await get_search_combo(query=query, limit=0, fresh=0)
    results = resp.get("data") or []
    if minseeders and minseeders > 0:
        results = [i for i in results if _to_int_seeders(i.get("seeders")) >= minseeders]
    return Response(_feed_xml(results, q, offset, limit), media_type="application/xml")


def _to_int_seeders(value):
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0
