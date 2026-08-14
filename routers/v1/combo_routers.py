import time
import asyncio

from fastapi import APIRouter, status
from typing import Optional

from helper.result_cleaner import (
    category_matches,
    clean_results,
    format_matches,
    language_matches,
    quality_matches,
    size_matches,
    sort_results,
)
from helper.is_site_available import check_if_site_available
from helper.error_messages import error_handler
from helper.search_cache import combo_cache
from helper.site_health import site_health

router = APIRouter(tags=["Combo Routes"])

SITE_DEADLINE = 40.0


async def _search_site(website, query, limit, page=1):
    return await website().search(query, page=page, limit=limit)


@router.get("/search")
async def get_search_combo(
    query: str,
    sites: Optional[str] = "",
    limit: Optional[int] = 0,
    page: Optional[int] = 1,
    fresh: Optional[int] = 0,
    dedup: Optional[int] = 0,
    include: Optional[str] = "", 
    min_seeders: Optional[int] = 0,
    category: Optional[str] = None,
    sort: Optional[str] = "seeders",
    order: Optional[str] = "desc",
    quality: Optional[str] = "",
    language: Optional[str] = "",
    format: Optional[str] = "",
    min_size: Optional[str] = "",
    max_size: Optional[str] = "",
):
    start_time = time.time()
    query = query.lower().strip()
    category = (category or "").lower().strip()
    sort = (sort or "seeders").lower()
    order = (order or "desc").lower()
    quality = (quality or "").lower().strip()
    language = (language or "").lower().strip()
    format = (format or "").lower().strip()
    include = (include or "").strip().lower()
    min_size = (min_size or "").strip().lower()
    max_size = (max_size or "").strip().lower()

    cache_key = (
        f"combo:{sites}:{query}:{page}:{limit}:{min_seeders}:{category}:{sort}:{order}"
        f":{quality}:{language}:{format}"
        f":{min_size}:{max_size}:{dedup}:{include}"
    )
    if not fresh:
        cached = combo_cache.get(cache_key)
        if cached is not None:
            cached["time"] = time.time() - start_time
            return clean_results(cached, sort=False, dedup=False)

    all_sites = check_if_site_available("1337x")
    if sites:
        sites_list = [
            site
            for site in (s.strip() for s in sites.split(","))
            if site in all_sites and all_sites[site].get("enabled", True)
        ]
    else:
        sites_list = [
            site
            for site in all_sites.keys()
            if all_sites[site].get("enabled", True)
            and all_sites[site].get("combo_available", True)
        ]
    # Sites whose results are pushed to the end of the combined list
    # (1337x search quality varies and the user wants its results last).
    LAST_SITES = {"1337x"}

    def _seeders(item):
        try:
            return float(str(item.get("seeders")).replace(",", "").strip())
        except (TypeError, ValueError):
            return -1

    def _apply_filters(
        items, min_seeders, category, quality, language, format_, min_size="", max_size="",
        include="",
    ):
        """Apply every active filter; returns the filtered list."""
        out = items
        if min_seeders > 0:
            out = [i for i in out if _seeders(i) >= min_seeders]
        if include:
            out = [i for i in out if include in str(i.get("name") or "").lower()]
        if category:
            out = [i for i in out if category_matches(i, category)]
        if quality:
            out = [i for i in out if quality_matches(i, quality)]
        if language:
            out = [i for i in out if language_matches(i, language)]
        if format:
            out = [i for i in out if format_matches(i, format)]
        if min_size or max_size:
            out = [i for i in out if size_matches(i, min_size, max_size)]
        return out

    def _relax_filters(
        items, min_seeders, category, quality, language, format_, min_size="", max_size="", include=""
    ):
        """When a strict filter combo leaves nothing (e.g. Hindi is only
        available in 4K but the user asked 1080p), relax filters in
        importance order - quality, then size, then format, then category.
        The language filter is NEVER relaxed away: a Hindi search must never
        silently return English releases. include is a hard filter too: the
        user asked for it explicitly. If nothing survives, return what
        keeps language + include (possibly empty)."""
        for drop in ("quality", "size", "format", "category"):
            relaxed = _apply_filters(
                items,
                min_seeders,
                "" if drop == "category" else category,
                "" if drop == "quality" else quality,
                language,
                "" if drop == "format" else format,
                "" if drop == "size" else min_size,
                "" if drop == "size" else max_size,
                include,
            )
            if relaxed:
                return relaxed, True
        return (
            _apply_filters(items, min_seeders, "", "", language, "", "", "", include),
            True,
        )

    main_data = []
    last_data = []
    total_torrents_overall = 0

    def _site_limit(site):
        site_limit = all_sites[site]["limit"]
        if limit > 0 and limit < site_limit:
            site_limit = limit
        return site_limit

    def _build_tasks(site_list):
        return [
            (
                site,
                asyncio.create_task(
                    _search_site(all_sites[site]["website"], query, _site_limit(site), page)
                ),
            )
            for site in site_list
        ]

    async def _collect(tasks):
        """Run site tasks under one deadline and merge their rows.
        Returns the sites that produced no data (slow/alive/empty/error)."""
        nonlocal total_torrents_overall
        done, pending = await asyncio.wait(
            [t for _, t in tasks], timeout=SITE_DEADLINE
        )
        for t in pending:
            t.cancel()
        missed = []
        for site, task in tasks:
            if task not in done:
                # Slow but alive: skip this round, don't blacklist.
                missed.append(site)
                continue
            try:
                res = task.result()
            except asyncio.CancelledError:
                missed.append(site)
                continue
            except Exception as e:
                site_health.mark_failure(site, e)
                missed.append(site)
                continue
            if res is None or not res.get("data"):
                missed.append(site)
                continue
            site_health.mark_success(site)
            bucket = last_data if site in LAST_SITES else main_data
            for item in res["data"]:
                if isinstance(item, dict) and "site" not in item:
                    item["site"] = site
                bucket.append(item)
            total_torrents_overall = total_torrents_overall + res["total"]
        return missed

    active_sites = [site for site in sites_list if not site_health.is_blocked(site)]
    missed = await _collect(_build_tasks(active_sites))

    def _site_guaranteed_dedup(items):
        """Every site keeps its top result so no site ever vanishes (the
        same popular release on 5 sites still shows all 5 sites), while
        extra results beyond the first-per-site are deduped by infohash
        so high limits don't fill the list with identical torrents."""
        guaranteed = {}
        seen = set()
        extras = []
        for item in items:
            site = item.get("site")
            h = str(item.get("hash") or "").strip().lower()
            if site not in guaranteed:
                guaranteed[site] = item
                if h:
                    seen.add(h)
            elif h and h in seen:
                continue
            else:
                if h:
                    seen.add(h)
                extras.append(item)
        return list(guaranteed.values()) + extras

    main_data.sort(key=_seeders, reverse=True)
    last_data.sort(key=_seeders, reverse=True)
    merged = main_data + last_data
    unique_data = _site_guaranteed_dedup(merged) if dedup else merged
    relaxed = False
    if unique_data:
        filtered = _apply_filters(
            unique_data, min_seeders, category, quality, language, format,
            min_size, max_size, include,
        )
        if not filtered and (category or quality or language or format or min_size or max_size):
            # Language-specific results live on a few sites (e.g. Hindi on
            # kickass/limetorrent); if those were slow/empty this round,
            # retry ONLY them before relaxing anything.
            if language and missed:
                # A site that failed hard got a cooldown from mark_failure;
                # retrying it immediately only wastes time, so retry the
                # slow/alive ones only.
                retry_candidates = [
                    s for s in missed if not site_health.is_blocked(s)
                ]
                if retry_candidates:
                    retry_missed = await _collect(_build_tasks(retry_candidates))
                    if retry_missed:
                        missed = retry_missed
                main_data.sort(key=_seeders, reverse=True)
                last_data.sort(key=_seeders, reverse=True)
                merged = main_data + last_data
                unique_data = _site_guaranteed_dedup(merged) if dedup else merged
                filtered = _apply_filters(
                    unique_data, min_seeders, category, quality, language, format,
                    min_size, max_size,
                )
            if not filtered:
                filtered, relaxed = _relax_filters(
                    unique_data, min_seeders, category, quality, language, format,
                    min_size, max_size, include,
                )
        unique_data = filtered
    sort_results(unique_data, sort=sort, order=order)
    COMBO = {"data": unique_data}
    if relaxed:
        COMBO["relaxed_filters"] = True
    COMBO["time"] = time.time() - start_time
    COMBO["total"] = len(COMBO["data"])
    if total_torrents_overall == 0:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Result not found."},
        )
    # Never cache an empty filtered result: a zero-row snapshot would keep
    # serving "No result found" from disk until its TTL expires.
    if COMBO["total"] > 0:
        combo_cache.set(cache_key, COMBO)
    return clean_results(COMBO, sort=False, dedup=False)


@router.get("/trending")
async def get_all_trending(
    limit: Optional[int] = 0, sites: Optional[str] = "", page: Optional[int] = 1
):
    start_time = time.time()
    # * just getting all_sites dictionary
    all_sites = check_if_site_available("1337x")
    if sites:
        sites_list = [
            site
            for site in (s.strip() for s in sites.split(","))
            if site in all_sites
            and all_sites[site].get("trending_available")
            and all_sites[site].get("website")
        ]
    else:
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
                        category=None, page=page, limit=site_limit
                    )
                ),
            )
        )
    done, pending = await asyncio.wait(
        [t for _, t in tasks], timeout=SITE_DEADLINE
    )
    for t in pending:
        t.cancel()
    for site, task in tasks:
        if task not in done:
            # Slow but alive: skip this round, don't blacklist (results matter).
            continue
        try:
            res = task.result()
        except asyncio.CancelledError:
            continue
        except Exception as e:
            site_health.mark_failure(site, e)
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
    if requested > 0:
        COMBO["data"] = COMBO["data"][:requested]
    if total_torrents_overall == 0:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Result not found."},
        )
    return clean_results(COMBO, dedup=False)


@router.get("/recent")
async def get_all_recent(
    limit: Optional[int] = 0, sites: Optional[str] = "", page: Optional[int] = 1
):
    start_time = time.time()
    # * just getting all_sites dictionary
    all_sites = check_if_site_available("1337x")
    if sites:
        sites_list = [
            site
            for site in (s.strip() for s in sites.split(","))
            if site in all_sites
            and all_sites[site].get("recent_available")
            and all_sites[site].get("website")
        ]
    else:
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
                        category=None, page=page, limit=site_limit
                    )
                ),
            )
        )
    done, pending = await asyncio.wait(
        [t for _, t in tasks], timeout=SITE_DEADLINE
    )
    for t in pending:
        t.cancel()
    for site, task in tasks:
        if task not in done:
            # Slow but alive: skip this round, don't blacklist (results matter).
            continue
        try:
            res = task.result()
        except asyncio.CancelledError:
            continue
        except Exception as e:
            site_health.mark_failure(site, e)
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
    if requested > 0:
        COMBO["data"] = COMBO["data"][:requested]
    if total_torrents_overall == 0:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Result not found."},
        )
    return clean_results(COMBO, dedup=False)
