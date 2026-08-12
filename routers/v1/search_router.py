import asyncio

from fastapi import APIRouter, status
from typing import Optional

from helper.result_cleaner import (
    category_matches,
    clean_results,
    format_matches,
    language_matches,
    quality_matches,
    sort_results,
)
from helper.is_site_available import check_if_site_available
from helper.error_messages import error_handler
from helper.search_cache import search_cache
from helper.site_health import site_health

router = APIRouter(tags=["Search"])

SITE_DEADLINE = 28.0


async def _search_site(website, query, page, limit):
    return await website().search(query, page, limit)


async def _search_with_retry(website, query, page, limit):
    """Try once, retry once on hard errors (fast failures). Timeouts are not
    retried - the site is slow but alive, so results still come next time."""
    for attempt in range(2):
        task = asyncio.create_task(_search_site(website, query, page, limit))
        try:
            return await asyncio.wait_for(task, timeout=SITE_DEADLINE)
        except asyncio.TimeoutError:
            task.cancel()
            raise
        except Exception:
            task.cancel()
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            raise


@router.get("/")
@router.get("")
async def search_for_torrents(
    site: str,
    query: str,
    limit: Optional[int] = 0,
    page: Optional[int] = 1,
    fresh: Optional[int] = 0,
    min_seeders: Optional[int] = 0,
    category: Optional[str] = None,
    sort: Optional[str] = "seeders",
    order: Optional[str] = "desc",
    quality: Optional[str] = "",
    language: Optional[str] = "",
    format: Optional[str] = "",
):
    site = site.lower().strip()
    query = query.lower().strip()
    category = (category or "").lower().strip()
    sort = (sort or "seeders").lower()
    order = (order or "desc").lower()
    quality = (quality or "").lower().strip()
    language = (language or "").lower().strip()
    format = (format or "").lower().strip()
    all_sites = check_if_site_available(site)
    if not all_sites:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Selected Site Not Available"},
        )

    limit = (
        all_sites[site]["limit"]
        if limit == 0 or limit > all_sites[site]["limit"]
        else limit
    )

    cache_key = (
        f"{site}:{query}:{page}:{limit}:{min_seeders}:{category}:{sort}:{order}"
        f":{quality}:{language}:{format}"
    )
    if not fresh:
        cached = search_cache.get(cache_key)
        if cached is not None:
            return clean_results(cached)

    try:
        resp = await _search_with_retry(
            all_sites[site]["website"], query, page, limit
        )
    except asyncio.TimeoutError:
        # Slow but alive: don't blacklist, retry next time (results matter).
        return error_handler(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            json_message={"error": "Site took too long to respond, try again."},
        )
    except Exception as e:
        site_health.mark_failure(site, e)
        return error_handler(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            json_message={"error": "Site is temporarily unavailable."},
        )

    if resp is None:
        return error_handler(
            status_code=status.HTTP_403_FORBIDDEN,
            json_message={"error": "Website Blocked Change IP or Website Domain."},
        )

    def _seeders(item):
        try:
            return float(str(item.get("seeders")).replace(",", "").strip())
        except (TypeError, ValueError):
            return -1

    def _apply_filters(items):
        out = items
        if min_seeders > 0:
            out = [i for i in out if _seeders(i) >= min_seeders]
        if category:
            out = [i for i in out if category_matches(i, category)]
        if quality:
            out = [i for i in out if quality_matches(i, quality)]
        if language:
            out = [i for i in out if language_matches(i, language)]
        if format:
            out = [i for i in out if format_matches(i, format)]
        return out

    data = _apply_filters(resp["data"])
    relaxed = False
    # A strict filter combo (e.g. Hindi + 1080p when the Hindi release is
    # only 4K) must not end in an empty "No result found" - relax quality,
    # then format, then language, then category and return what exists.
    if not data and resp["data"] and (category or quality or language or format):
        for drop in ("quality", "format", "language", "category"):
            q2 = "" if drop == "quality" else quality
            f2 = "" if drop == "format" else format
            l2 = "" if drop == "language" else language
            c2 = "" if drop == "category" else category
            relaxed_data = [
                item
                for item in resp["data"]
                if (min_seeders <= 0 or _seeders(item) >= min_seeders)
                and (not c2 or category_matches(item, c2))
                and (not q2 or quality_matches(item, q2))
                and (not l2 or language_matches(item, l2))
                and (not f2 or format_matches(item, f2))
            ]
            if relaxed_data:
                data = relaxed_data
                relaxed = True
                break
        if not data:
            data = [i for i in resp["data"] if (min_seeders <= 0 or _seeders(i) >= min_seeders)]
            relaxed = True
    sort_results(data, sort=sort, order=order)
    resp["data"] = data
    resp["total"] = len(data)
    if relaxed:
        resp["relaxed_filters"] = True
    if len(resp["data"]) > 0:
        site_health.mark_success(site)
        search_cache.set(cache_key, resp)
        return clean_results(resp)

    return error_handler(
        status_code=status.HTTP_404_NOT_FOUND,
        json_message={"error": "Result not found."},
    )
