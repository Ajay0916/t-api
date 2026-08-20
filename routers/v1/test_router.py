"""Built-in site / mirror health tester.

GET /api/v1/test?site=magnetdl
  → Tests the site via plain HTTP, then optionally via FlareSolverr.
  → Returns status, timing, content size, CF detection, etc.

Params:
  site   (str, required)  — site key from all_sites
  url    (str, optional)  — override URL to test (mirror / custom)
  flare  (int, 0|1)      — also test via FlareSolverr (default 0)
  query  (str, optional)  — test query for actual search (default "python")
"""

import asyncio
from helper.logging_setup import get_logger
LOGGER = get_logger("tapi.test")
import os
import re
import time

from fastapi import APIRouter, Query
from typing import Optional

from helper.plain_curl import fetch_plain, _is_cf_challenge
from helper.is_site_available import all_sites
from helper.version_info import get_version_info

router = APIRouter(tags=["Test"])

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")


async def _test_plain(url, timeout=12):
    """Plain HTTP fetch via curl — no browser."""
    t0 = time.time()
    html = await fetch_plain(url, timeout=timeout)
    elapsed = round(time.time() - t0, 2)
    if not html:
        return {
            "method": "plain",
            "status": "TIMEOUT/ERROR",
            "http_code": 0,
            "size": 0,
            "cf_challenge": False,
            "elapsed": elapsed,
        }
    # Detect CF challenge
    cf = _is_cf_challenge(html)
    return {
        "method": "plain",
        "status": "OK" if not cf else "CF_BLOCKED",
        "http_code": 200,
        "size": len(html),
        "cf_challenge": cf,
        "elapsed": elapsed,
        "preview": html[:150].replace("\n", " ").strip(),
    }


async def _test_flare(url, timeout=35):
    """FlareSolverr browser fetch."""
    import aiohttp
    from helper.session import get_connector

    t0 = time.time()
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": 30000,
    }
    try:
        async with aiohttp.ClientSession(
            connector=get_connector(), connector_owner=False, trust_env=True
        ) as session:
            async with session.post(
                f"{FLARESOLVERR_URL}/v1",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as res:
                data = await res.json(content_type=None)
        elapsed = round(time.time() - t0, 2)
        solution = data.get("solution") or {}
        status_code = solution.get("status", 0)
        html = solution.get("response", "")
        cf = _is_cf_challenge(html) if html else True
        return {
            "method": "flaresolverr",
            "status": data.get("status", "unknown"),
            "http_code": status_code,
            "size": len(html),
            "cf_challenge": cf,
            "elapsed": elapsed,
            "preview": html[:150].replace("\n", " ").strip() if html else "",
        }
    except Exception as e:
        return {
            "method": "flaresolverr",
            "status": f"ERROR: {type(e).__name__}",
            "http_code": 0,
            "size": 0,
            "cf_challenge": False,
            "elapsed": round(time.time() - t0, 2),
            "error": str(e)[:100],
        }


async def _test_search(site_key, query, limit=1):
    """Run actual search and return results count + timing."""
    site_info = all_sites.get(site_key)
    if not site_info:
        return {"error": f"Site '{site_key}' not found"}
    website = site_info["website"]
    t0 = time.time()
    try:
        result = await asyncio.wait_for(
            website().search(query, 1, limit), timeout=40
        )
        elapsed = round(time.time() - t0, 2)
        if result is None:
            return {"search": "None", "results": 0, "elapsed": elapsed}
        data = result.get("data") or []
        return {
            "search": "OK",
            "results": len(data),
            "elapsed": elapsed,
            "sample": data[0].get("name", "")[:60] if data else "",
        }
    except asyncio.TimeoutError:
        return {"search": "TIMEOUT", "results": 0, "elapsed": round(time.time() - t0, 2)}
    except Exception as e:
        return {"search": f"ERROR: {type(e).__name__}", "results": 0, "error": str(e)[:100], "elapsed": round(time.time() - t0, 2)}


@router.get("")
async def test_site(
    site: str = Query(..., description="Site key (e.g. magnetdl, 1337x)"),
    url: Optional[str] = Query(None, description="Override URL to test (mirror)"),
    flare: Optional[int] = Query(0, description="Also test via FlareSolverr"),
    query: Optional[str] = Query("python", description="Search query for live test"),
    limit: Optional[int] = Query(1, description="Result limit for live test"),
    skip_search: Optional[int] = Query(0, description="Skip live search test"),
):
    site_info = all_sites.get(site)
    LOGGER.info("Test: site=" + site + " url=" + (url or "default") + " flare=" + str(flare))
    if not site_info:
        available = list(all_sites.keys())
        return {
            "error": f"Site '{site}' not found",
            "available": available,
        }

    base_url = None
    # Try to get the site's BASE_URL
    try:
        obj = site_info["website"]()
        base_url = getattr(obj, "BASE_URL", None)
    except Exception:
        pass

    test_url = url or base_url or "https://example.com"

    results = get_version_info()
    results.update({
        "site": site,
        "name": site_info["website"]._name,
        "test_url": test_url,
    })

    # Plain HTTP test
    plain = await _test_plain(test_url)
    results["plain"] = plain

    # FlareSolverr test
    if flare:
        flare_result = await _test_flare(test_url)
        results["flaresolverr"] = flare_result

    # Live search test
    if not skip_search:
        search_result = await _test_search(site, query, limit)
        results["search_test"] = search_result

    return results


@router.get("/url")
async def test_url(
    url: str = Query(..., description="URL to test"),
    flare: Optional[int] = Query(0, description="Also test via FlareSolverr"),
):
    """Test any arbitrary URL — plain + optional FlareSolverr."""
    results = get_version_info()
    results["test_url"] = url
    results["plain"] = await _test_plain(url)
    if flare:
        results["flaresolverr"] = await _test_flare(url)
    return results


@router.get("/all")
async def test_all_sites(
    query: Optional[str] = Query("python", description="Search query"),
    limit: Optional[int] = Query(1, description="Result limit per site"),
    flare: Optional[int] = Query(0, description="Also test FlareSolverr on each"),
):
    """Test all registered sites — returns summary of each."""
    LOGGER.info(f"Test all: {len(all_sites)} sites, query={query}")
    results = []
    version_info = get_version_info()
    for key, info in all_sites.items():
        obj = info["website"]()
        base_url = getattr(obj, "BASE_URL", None)
        entry = {"site": key, "name": info["website"]._name, "url": base_url}

        # Plain test
        if base_url:
            entry["plain"] = await _test_plain(base_url, timeout=8)
        else:
            entry["plain"] = {"status": "NO_URL", "elapsed": 0}

        # Search test
        search_result = await _test_search(key, query, limit)
        entry["search_test"] = search_result

        # Flare test
        if flare and base_url:
            entry["flaresolverr"] = await _test_flare(base_url, timeout=25)

        results.append(entry)

    resp = get_version_info()
    resp.update({
        "total": len(results),
        "sites": results,
    })
    return resp
