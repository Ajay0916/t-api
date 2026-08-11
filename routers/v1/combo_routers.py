import time
import asyncio

from fastapi import APIRouter, status
from typing import Optional

from helper.result_cleaner import clean_results
from helper.is_site_available import check_if_site_available
from helper.error_messages import error_handler
from helper.search_cache import combo_cache
from helper.site_health import site_health

router = APIRouter(tags=["Combo Routes"])

SITE_DEADLINE = 12.0


async def _search_site(website, query, limit):
    return await website().search(query, page=1, limit=limit)


@router.get("/search")
async def get_search_combo(
    query: str, limit: Optional[int] = 0, fresh: Optional[int] = 0
):
    start_time = time.time()
    query = query.lower()

    cache_key = f"combo:{query}:{limit}"
    if not fresh:
        cached = combo_cache.get(cache_key)
        if cached is not None:
            cached["time"] = time.time() - start_time
            return clean_results(cached, sort=False)

    all_sites = check_if_site_available("1337x")
    sites_list = [
        site
        for site in all_sites.keys()
        if all_sites[site].get("combo_available", True)
    ]
    # Sites whose results are pushed to the end of the combined list
    # (1337x search quality varies and the user wants its results last).
    LAST_SITES = {"1337x"}

    def _seeders(item):
        try:
            return float(str(item.get("seeders")).replace(",", "").strip())
        except (TypeError, ValueError):
            return -1

    main_data = []
    last_data = []
    total_torrents_overall = 0

    tasks = []
    for site in sites_list:
        if site_health.is_blocked(site):
            continue
        site_limit = all_sites[site]["limit"]
        if limit > 0 and limit < site_limit:
            site_limit = limit
        tasks.append(
            (
                site,
                asyncio.create_task(
                    _search_site(all_sites[site]["website"], query, site_limit)
                ),
            )
        )

    for site, task in tasks:
        try:
            res = await asyncio.wait_for(task, timeout=SITE_DEADLINE)
        except Exception:
            site_health.mark_failure(site)
            continue
        if res is None:
            continue
        if len(res["data"]) > 0:
            site_health.mark_success(site)
            bucket = last_data if site in LAST_SITES else main_data
            bucket.extend(res["data"])
            total_torrents_overall = total_torrents_overall + res["total"]

    main_data.sort(key=_seeders, reverse=True)
    last_data.sort(key=_seeders, reverse=True)
    COMBO = {"data": main_data + last_data}
    COMBO["time"] = time.time() - start_time
    COMBO["total"] = total_torrents_overall
    if total_torrents_overall == 0:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Result not found."},
        )
    combo_cache.set(cache_key, COMBO)
    return clean_results(COMBO, sort=False)


@router.get("/trending")
async def get_all_trending(limit: Optional[int] = 0):
    start_time = time.time()
    # * just getting all_sites dictionary
    all_sites = check_if_site_available("1337x")
    sites_list = [
        site
        for site in all_sites.keys()
        if all_sites[site].get("trending_available")
        and all_sites[site].get("website")
    ]
    COMBO = {"data": []}
    total_torrents_overall = 0
    tasks = []
    requested = limit
    for site in sites_list:
        site_limit = all_sites[site]["limit"]
        if requested > 0 and requested < site_limit:
            site_limit = requested
        if site_health.is_blocked(site):
            continue
        tasks.append(
            (
                site,
                asyncio.create_task(
                    all_sites[site]["website"]().trending(
                        category=None, page=1, limit=site_limit
                    )
                ),
            )
        )
    for site, task in tasks:
        try:
            res = await asyncio.wait_for(task, timeout=SITE_DEADLINE)
        except Exception:
            site_health.mark_failure(site)
            continue
        if res is None:
            continue
        if len(res["data"]) > 0:
            site_health.mark_success(site)
            for torrent in res["data"]:
                COMBO["data"].append(torrent)
            total_torrents_overall = total_torrents_overall + res["total"]
    COMBO["time"] = time.time() - start_time
    COMBO["total"] = total_torrents_overall
    if total_torrents_overall == 0:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Result not found."},
        )
    return clean_results(COMBO)


@router.get("/recent")
async def get_all_recent(limit: Optional[int] = 0):
    start_time = time.time()
    # * just getting all_sites dictionary
    all_sites = check_if_site_available("1337x")
    sites_list = [
        site
        for site in all_sites.keys()
        if all_sites[site].get("recent_available")
        and all_sites[site].get("website")
    ]
    COMBO = {"data": []}
    total_torrents_overall = 0
    tasks = []
    requested = limit
    for site in sites_list:
        site_limit = all_sites[site]["limit"]
        if requested > 0 and requested < site_limit:
            site_limit = requested
        if site_health.is_blocked(site):
            continue
        tasks.append(
            (
                site,
                asyncio.create_task(
                    all_sites[site]["website"]().recent(
                        category=None, page=1, limit=site_limit
                    )
                ),
            )
        )
    for site, task in tasks:
        try:
            res = await asyncio.wait_for(task, timeout=SITE_DEADLINE)
        except Exception:
            site_health.mark_failure(site)
            continue
        if res is None:
            continue
        if len(res["data"]) > 0:
            site_health.mark_success(site)
            for torrent in res["data"]:
                COMBO["data"].append(torrent)
            total_torrents_overall = total_torrents_overall + res["total"]
    COMBO["time"] = time.time() - start_time
    COMBO["total"] = total_torrents_overall
    if total_torrents_overall == 0:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Result not found."},
        )
    return clean_results(COMBO)
