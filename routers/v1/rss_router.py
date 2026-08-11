import asyncio
import time
from typing import Optional
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import APIRouter, Response, status

from helper.error_messages import error_handler
from helper.is_site_available import check_if_site_available
from helper.search_cache import rss_cache
from helper.site_health import site_health

router = APIRouter(tags=["RSS"])

SITE_DEADLINE = 12.0


def _seeders(item):
    try:
        return float(str(item.get("seeders")).replace(",", "").strip())
    except (TypeError, ValueError):
        return -1


def _item_xml(item):
    name = escape(str(item.get("name") or "Untitled"))
    url = escape(str(item.get("url") or ""))
    desc_bits = []
    if item.get("size"):
        desc_bits.append("Size: " + escape(str(item["size"])))
    if item.get("seeders") is not None:
        desc_bits.append("Seeders: {}".format(item["seeders"]))
    if item.get("leechers") is not None:
        desc_bits.append("Leechers: {}".format(item["leechers"]))
    if item.get("category"):
        desc_bits.append("Category: " + escape(str(item["category"])))
    magnet = item.get("magnet")
    torrent = item.get("torrent")
    if magnet:
        desc_bits.append(
            'Magnet: <a href="{}">download magnet</a>'.format(escape(str(magnet)))
        )
    if torrent:
        desc_bits.append(
            'Torrent: <a href="{}">.torrent file</a>'.format(escape(str(torrent)))
        )
    guid = escape(str(item.get("hash") or item.get("url") or item.get("name") or ""))
    return (
        "<item>"
        "<title>{}</title>"
        "<link>{}</link>"
        '<guid isPermaLink="false">{}</guid>'
        "<description>{}</description>"
        "</item>"
    ).format(name, url, guid, "<br/>".join(desc_bits))


async def _search_site(website, query, limit):
    return await website().search(query, page=1, limit=limit)


def _build_feed(query, site, limit, items):
    link = "http://localhost:8009/api/v1/rss?query={}&amp;site={}&amp;limit={}".format(
        quote(query), quote(site), limit
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
        "<channel>"
        "<title>Torrents API — {}</title>"
        "<link>{}</link>"
        "<description>Torrent / Books / Courses search results from Torrents API</description>"
        "<language>en-us</language>"
        '<atom:link href="{}" rel="self" type="application/rss+xml"/>'
    ).format(escape(query), link, link)
    xml += "".join(_item_xml(item) for item in items)
    xml += "</channel></rss>"
    return xml


@router.get("/")
@router.get("")
async def rss_feed(
    query: str,
    site: Optional[str] = "all",
    limit: Optional[int] = 20,
    fresh: Optional[int] = 0,
):
    query = query.lower().strip()
    site = (site or "all").lower()
    limit = max(1, min(limit or 20, 100))

    cache_key = "rss:{}:{}:{}".format(site, query, limit)
    if not fresh:
        cached = rss_cache.get(cache_key)
        if cached is not None:
            return Response(content=cached, media_type="application/rss+xml")

    all_sites = check_if_site_available(site if site != "all" else "1337x")
    if not all_sites:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Selected Site Not Available"},
        )

    start = time.time()
    if site == "all":
        sites_list = [
            key
            for key, info in all_sites.items()
            if info.get("combo_available", True) and info.get("website")
        ]
        main_data = []
        last_data = []
        tasks = []
        for key in sites_list:
            if site_health.is_blocked(key):
                continue
            site_limit = all_sites[key]["limit"]
            if limit < site_limit:
                site_limit = limit
            tasks.append(
                (
                    key,
                    asyncio.create_task(
                        _search_site(all_sites[key]["website"], query, site_limit)
                    ),
                )
            )
        for key, task in tasks:
            try:
                res = await asyncio.wait_for(task, timeout=SITE_DEADLINE)
            except Exception:
                site_health.mark_failure(key)
                continue
            if res is None or not res.get("data"):
                continue
            site_health.mark_success(key)
            bucket = last_data if key == "1337x" else main_data
            bucket.extend(res["data"])
        main_data.sort(key=_seeders, reverse=True)
        last_data.sort(key=_seeders, reverse=True)
        items = (main_data + last_data)[:limit]
    else:
        try:
            res = await asyncio.wait_for(
                _search_site(all_sites[site]["website"], query, limit),
                timeout=28,
            )
        except Exception:
            site_health.mark_failure(site)
            return error_handler(
                status_code=status.HTTP_502_BAD_GATEWAY,
                json_message={"error": "Site is temporarily unavailable."},
            )
        if res is None or not res.get("data"):
            return error_handler(
                status_code=status.HTTP_404_NOT_FOUND,
                json_message={"error": "Result not found."},
            )
        site_health.mark_success(site)
        items = res["data"][:limit]

    if not items:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Result not found."},
        )

    feed = _build_feed(query, site, limit, items)
    rss_cache.set(cache_key, feed)
    return Response(content=feed, media_type="application/rss+xml; charset=utf-8")
