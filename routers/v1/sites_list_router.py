from fastapi import APIRouter, status
from helper.is_site_available import check_if_site_available, sites_config
from helper.error_messages import error_handler
from helper.site_health import site_health

router = APIRouter(tags=["Get all sites"])


@router.get("/")
@router.get("")
async def get_all_supported_sites():
    all_sites = check_if_site_available("1337x")
    sites_list = []
    sites = []
    for site, info in all_sites.items():
        if (
            not info["website"]
            or info.get("enabled", True) is False
            or site_health.is_manually_blocked(site)
        ):
            continue
        sites_list.append(site)
        sites.append(
            {
                "site": site,
                "name": info["website"]._name,
            }
        )
    return error_handler(
        status_code=status.HTTP_200_OK,
        json_message={
            "supported_sites": sites_list,
            "sites": sites,
        },
    )
    
@router.get("/config")
async def get_site_config():
    return error_handler(
        status_code=status.HTTP_200_OK,
        json_message=sites_config
    )


@router.get("/status")
async def get_site_status():
    all_sites = check_if_site_available("1337x")
    sites = []
    for key, info in all_sites.items():
        if not info.get("website"):
            continue
        health = site_health.status(key)
        manual = bool(health.get("manual_blocked"))
        sites.append(
            {
                "site": key,
                "name": info["website"]._name,
                "enabled": not manual,
                "manual_blocked": manual,
                "blocked": health["blocked"],
                "cooldown_remaining": health["cooldown_remaining"],
                "fail_count": health["fail_count"],
                "last_error": health.get("last_error", ""),
                "combo_available": info.get("combo_available", True),
                "trending_available": info.get("trending_available", False),
                "recent_available": info.get("recent_available", False),
                "limit": info.get("limit"),
            }
        )
    enabled = sum(1 for s in sites if s["enabled"])
    return error_handler(
        status_code=status.HTTP_200_OK,
        json_message={
            "total": len(sites),
            "enabled": enabled,
            "disabled": len(sites) - enabled,
            "sites": sites,
        },
    )
