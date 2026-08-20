from fastapi import APIRouter
from helper.logging_setup import get_logger
LOGGER = get_logger("tapi.magnet")
from fastapi.responses import JSONResponse, RedirectResponse

from helper.short_links import lookup

router = APIRouter(tags=["Magnet Short"])


@router.get("/{token}")
async def magnet_short(token: str):
    """Resolve a short magnet token to the real magnet (302 redirect)."""
    info = lookup(token)
    url = (info or {}).get("url") or ""
    if not str(url).startswith("magnet:"):
        return JSONResponse(status_code=404, content={"error": "Link not found."})
    return RedirectResponse(url=url, status_code=302)
