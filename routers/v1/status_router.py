import time

from fastapi import APIRouter

_START = time.time()

from helper.is_site_available import check_if_site_available
from helper.site_health import site_health
from helper.uptime import getUptime

router = APIRouter(tags=["Status"])


@router.get("")
async def get_status():
    all_sites = check_if_site_available("1337x") or {}
    sites = {}
    blocked = 0
    for name, cfg in all_sites.items():
        st = site_health.status(name)
        sites[name] = {
            "enabled": not st.get("manual_blocked", False),
            "blocked": st["blocked"],
            "manual_blocked": st.get("manual_blocked", False),
            "cooldown_remaining": st["cooldown_remaining"],
            "fail_count": st["fail_count"],
            "last_error": st.get("last_error", ""),
            "combo_available": bool(cfg.get("combo_available", True)),
            "limit": cfg.get("limit"),
        }
        if st["blocked"]:
            blocked += 1
    return {
        "sites": len(sites),
        "blocked_sites": blocked,
        "healthy_sites": len(sites) - blocked,
        "uptime": int(getUptime(_START)),
        "sites_detail": sites,
    }


@router.post("/{site}/disable")
async def disable_site(site: str):
    """Manually disable a site without restarting the server."""
    all_sites = check_if_site_available(site)
    if not all_sites:
        return {"error": "Site not available."}
    site_health.manual_block(site)
    return {"site": site, "disabled": True}


@router.post("/{site}/enable")
async def enable_site(site: str):
    """Re-enable a manually disabled site."""
    all_sites = check_if_site_available(site)
    if not all_sites:
        return {"error": "Site not available."}
    site_health.manual_unblock(site)
    return {"site": site, "disabled": False}
