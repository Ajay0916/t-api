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
            "blocked": st["blocked"],
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
