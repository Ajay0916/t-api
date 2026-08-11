import asyncio

from fastapi import APIRouter, status
from typing import Optional

from helper.result_cleaner import clean_results
from helper.is_site_available import check_if_site_available
from helper.error_messages import error_handler
from helper.search_cache import search_cache
from helper.site_health import site_health

router = APIRouter(tags=["Search"])

SITE_DEADLINE = 28.0


async def _search_site(website, query, page, limit):
    return await website().search(query, page, limit)


@router.get("/")
@router.get("")
async def search_for_torrents(
    site: str,
    query: str,
    limit: Optional[int] = 0,
    page: Optional[int] = 1,
    fresh: Optional[int] = 0,
):
    site = site.lower()
    query = query.lower()
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

    cache_key = f"{site}:{query}:{page}:{limit}"
    if not fresh:
        cached = search_cache.get(cache_key)
        if cached is not None:
            return clean_results(cached)

    task = asyncio.create_task(
        _search_site(all_sites[site]["website"], query, page, limit)
    )
    try:
        resp = await asyncio.wait_for(task, timeout=SITE_DEADLINE)
    except asyncio.TimeoutError:
        task.cancel()
        site_health.mark_failure(site)
        return error_handler(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            json_message={"error": "Site took too long to respond, try again."},
        )
    except Exception:
        site_health.mark_failure(site)
        return error_handler(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            json_message={"error": "Site is temporarily unavailable."},
        )

    if resp is None:
        return error_handler(
            status_code=status.HTTP_403_FORBIDDEN,
            json_message={"error": "Website Blocked Change IP or Website Domain."},
        )
    if len(resp["data"]) > 0:
        site_health.mark_success(site)
        search_cache.set(cache_key, resp)
        return clean_results(resp)

    return error_handler(
        status_code=status.HTTP_404_NOT_FOUND,
        json_message={"error": "Result not found."},
    )
