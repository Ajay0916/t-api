import asyncio

from fastapi import APIRouter, status
from typing import Optional

from helper.result_cleaner import category_matches, clean_results, sort_results
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
):
    site = site.lower().strip()
    query = query.lower().strip()
    category = (category or "").lower().strip()
    sort = (sort or "seeders").lower()
    order = (order or "desc").lower()
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

    cache_key = f"{site}:{query}:{page}:{limit}:{min_seeders}:{category}:{sort}:{order}"
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

    data = [
        item
        for item in resp["data"]
        if (min_seeders <= 0 or _seeders(item) >= min_seeders)
        and (not category or category_matches(item, category))
    ]
    sort_results(data, sort=sort, order=order)
    resp["data"] = data
    resp["total"] = len(data)
    if len(resp["data"]) > 0:
        site_health.mark_success(site)
        search_cache.set(cache_key, resp)
        return clean_results(resp)

    return error_handler(
        status_code=status.HTTP_404_NOT_FOUND,
        json_message={"error": "Result not found."},
    )
