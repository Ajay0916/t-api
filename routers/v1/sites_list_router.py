from fastapi import APIRouter, status
from helper.is_site_available import check_if_site_available, sites_config
from helper.error_messages import error_handler
from helper.site_health import site_health

router = APIRouter(tags=["Get all sites"])


@router.get("/")
@router.get("")
async def get_all_supported_sites():
    all_sites = check_if_site_available("1337x")
    sites_list = [site for site in all_sites.keys() if all_sites[site]["website"]]
    return error_handler(
        status_code=status.HTTP_200_OK,
        json_message={
            "supported_sites": sites_list,
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
        sites.append(
            {
                "site": key,
                "name": info["website"]._name,
                "blocked": health["blocked"],
                "cooldown_remaining": health["cooldown_remaining"],
                "fail_count": health["fail_count"],
                "combo_available": info.get("combo_available", True),
                "trending_available": info.get("trending_available", False),
                "recent_available": info.get("recent_available", False),
                "limit": info.get("limit"),
            }
        )
    return error_handler(
        status_code=status.HTTP_200_OK,
        json_message={"sites": sites},
    )
