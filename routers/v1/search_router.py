import asyncio
from helper.logging_setup import get_logger
LOGGER = get_logger("tapi.search")
import re
import time

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
from helper.search_cache import search_cache
from helper.site_health import site_health

router = APIRouter(tags=["Search"])

SITE_DEADLINE = 40.0
MAX_AUTO_LIMIT = 300
MAX_PAGES = 6


async def _search_site(website, query, page, limit):
    return await website().search(query, page, limit)


async def _search_with_retry(website, query, page, limit, deadline):
    """Try once, retry once on hard errors (fast failures). Timeouts are not
    retried - the site is slow but alive, so results still come next time."""
    for attempt in range(2):
        task = asyncio.create_task(_search_site(website, query, page, limit))
        try:
            return await asyncio.wait_for(task, timeout=deadline)
        except asyncio.TimeoutError:
            task.cancel()
            raise
        except Exception:
            task.cancel()
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            raise


def _parse_page(spec):
    """-p 0 -> unlimited pages, -p N -> single page N, -p A-B -> pages A..B."""
    m = re.match(r"^(\d+)(?:-(\d+))?$", (spec or "1").strip().lower())
    if not m:
        return 1, 1
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    if a <= 0:
        a, b = 1, MAX_PAGES
    elif b <= 0:
        b = MAX_PAGES
    if b < a:
        b = a
    return a, min(b, a + MAX_PAGES - 1)


async def _search_paginated(website, query, start_page, end_page, per_page, want, deadline):
    """Fetch pages until `want` results are collected (or pages run out).

    Single call when want <= per_page (backward compatible). Multi-page mode
    dedupes by url/hash/magnet/name across pages, so scrapers that ignore the
    page param safely stop after the first duplicate page.
    """
    if want <= per_page:
        return await _search_with_retry(website, query, start_page, per_page, deadline)

    started = time.monotonic()
    expires_at = started + deadline
    site_name = getattr(website, "_name", website.__name__ if isinstance(website, type) else str(website))
    rows, seen, total_pages = [], set(), 1
    resp = None
    for p in range(start_page, end_page + 1):
        try:
            remaining = max(1.0, expires_at - time.monotonic())
            page_started = time.monotonic()
            LOGGER.info("[TEMP-TIMING] page-start site=%s page=%s remaining=%.2f", site_name, p, remaining)
            resp = await _search_with_retry(website, query, p, per_page, remaining)
            LOGGER.info("[TEMP-TIMING] page-done page=%s duration=%.2f rows=%s", p, time.monotonic() - page_started, len((resp or {}).get("data") or []))
        except asyncio.TimeoutError:
            if p == start_page:
                raise
            break
        except Exception:
            if p == start_page:
                raise
            break
        if resp is None or not isinstance(resp, dict):
            if p == start_page:
                return None
            break
        data = resp.get("data") or []
        try:
            tp = int(resp.get("total_pages") or 1)
            total_pages = max(total_pages, tp)
        except (TypeError, ValueError):
            pass
        new = 0
        for it in data:
            key = it.get("url") or it.get("hash") or it.get("magnet") or it.get("name") or ""
            if key:
                if key in seen:
                    continue
                seen.add(key)
            rows.append(it)
            new += 1
        if len(rows) >= want or new == 0 or p >= end_page:
            break
    return {
        "data": rows,
        "current_page": start_page,
        "total_pages": total_pages,
        "total": len(rows),
        "time": time.time() - (time.monotonic() - started),
    }


@router.get("/")
@router.get("")
async def search_for_torrents(
    site: str,
    query: str,
    limit: Optional[int] = 0,
    page: Optional[str] = "1",
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
    timeout: Optional[float] = 0.0,
):
    site = site.lower().strip()
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
    # Special case: _restart triggers t-API restart (before site check)
    if site == "_restart":
        import subprocess as _sp, threading, time as _time
        repo = os.path.dirname(os.path.abspath(__file__)).replace("/routers/v1", "")
        def _bg():
            _time.sleep(1)
            env = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
            try:
                _sp.run(["/usr/bin/git", "fetch", "origin"], cwd=repo, timeout=20, env=env, capture_output=True)
                _sp.run(["/usr/bin/git", "reset", "--hard", "origin/main"], cwd=repo, timeout=10, env=env, capture_output=True)
                try:
                    commit = _sp.check_output(["/usr/bin/git", "rev-parse", "--short", "HEAD"], cwd=repo, timeout=5, env=env).decode().strip()
                    msg = _sp.check_output(["/usr/bin/git", "log", "-1", "--pretty=%s"], cwd=repo, timeout=5, env=env).decode().strip()
                    date = _sp.check_output(["/usr/bin/git", "log", "-1", "--pretty=%ci"], cwd=repo, timeout=5, env=env).decode().strip()
                    with open(os.path.join(repo, "COMMIT_INFO"), "w") as f:
                        f.write(f"{commit}\n{msg}\n{date}")
                except Exception:
                    pass
                _time.sleep(1)
                _sp.run(["systemctl", "restart", "t-api"], timeout=10, env=env, capture_output=True)
            except Exception:
                pass
        import threading
        threading.Thread(target=_bg, daemon=True).start()
        return {"data": [{"name": "✅ t-API Restarting...", "url": "#", "category": "System"}], "current_page": 1, "total_pages": 1, "time": 0.1, "total": 1}

    all_sites = check_if_site_available(site)
    if not all_sites:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Selected Site Not Available"},
        )

    if site_health.is_manually_blocked(site):
        return error_handler(
            status_code=status.HTTP_403_FORBIDDEN,
            json_message={"error": "Site is disabled."},
        )

    site_max = all_sites[site]["limit"]
    want = MAX_AUTO_LIMIT if limit == 0 else min(limit, MAX_AUTO_LIMIT)
    per_page = min(site_max, want)
    start_page, end_page = _parse_page(page)

    cache_key = (
        f"{site}:{query}:{page}:{want}:{min_seeders}:{category}:{sort}:{order}"
        f":{quality}:{language}:{format}:{min_size}:{max_size}:{dedup}:{include}:{timeout}"
    )
    if not fresh:
        cached = search_cache.get(cache_key)
        if cached is not None:
            return clean_results(cached, dedup=bool(dedup))

    LOGGER.info(f"Search: site={site} query={query[:40]} limit={want}")
    try:
        deadline = timeout if timeout and timeout > 0 else SITE_DEADLINE
        resp = await _search_paginated(
            all_sites[site]["website"], query, start_page, end_page, per_page, want, deadline
        )
    except asyncio.TimeoutError:
        # Slow but alive: don't blacklist, retry next time (results matter).
        LOGGER.warning(f"Timeout: {site} query={query[:30]}")
        return error_handler(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            json_message={"error": "Site took too long to respond, try again."},
        )
    except Exception as e:
        LOGGER.error(f"Error: {site} query={query[:30]} - {e}")
        site_health.mark_failure(site, e)
        return error_handler(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            json_message={"error": "Site is temporarily unavailable."},
        )

    if resp is None:
        return error_handler(
            status_code=status.HTTP_403_FORBIDDEN,
            json_message={
                "error": "Site is temporarily blocked or unreachable. Try again in a few minutes."
            },
        )

    def _seeders(item):
        try:
            return float(str(item.get("seeders")).replace(",", "").strip())
        except (TypeError, ValueError):
            return -1

    def _has_seeders(item):
        try:
            float(str(item.get("seeders")).replace(",", "").strip())
            return True
        except (TypeError, ValueError):
            return False

    def _apply_filters(items):
        out = items
        if min_seeders > 0:
            out = [i for i in out if not _has_seeders(i) or _seeders(i) >= min_seeders]
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

    data = _apply_filters(resp["data"])
    relaxed = False
    # A strict filter combo (e.g. Hindi + 1080p when the Hindi release is
    # only 4K) must not end in an empty "No result found" - relax quality,
    # then format, then category. The language filter is NEVER relaxed:
    # a Hindi search must never silently return English releases.
    if not data and resp["data"] and (
        category or quality or language or format or min_size or max_size
    ):
        for drop in ("quality", "size", "format", "category"):
            q2 = "" if drop == "quality" else quality
            s_min = "" if drop == "size" else min_size
            s_max = "" if drop == "size" else max_size
            f2 = "" if drop == "format" else format
            c2 = "" if drop == "category" else category
            relaxed_data = [
                item
                for item in resp["data"]
                if (min_seeders <= 0 or not _has_seeders(item) or _seeders(item) >= min_seeders)
                and (not include or include in str(item.get("name") or "").lower())
                and (not c2 or category_matches(item, c2))
                and (not q2 or quality_matches(item, q2))
                and (not language or language_matches(item, language))
                and (not f2 or format_matches(item, f2))
                and (not (s_min or s_max) or size_matches(item, s_min, s_max))
            ]
            if relaxed_data:
                data = relaxed_data
                relaxed = True
                break
        if not data:
            data = [
                item
                for item in resp["data"]
                if (min_seeders <= 0 or not _has_seeders(item) or _seeders(item) >= min_seeders)
                and (not include or include in str(item.get("name") or "").lower())
                and (not language or language_matches(item, language))
            ]
            relaxed = True
    sort_results(data, sort=sort, order=order)
    resp["data"] = data
    resp["total"] = len(data)
    if relaxed:
        resp["relaxed_filters"] = True
    if len(resp["data"]) > 0:
        site_health.mark_success(site)
        LOGGER.info(f"Results: {site} -> {len(resp.get('data') or [])} items")
        search_cache.set(cache_key, resp)
        return clean_results(resp, dedup=bool(dedup))

    return error_handler(
        status_code=status.HTTP_404_NOT_FOUND,
        json_message={"error": "Result not found."},
    )
