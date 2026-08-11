import os

import aiohttp
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["Download"])

_KEY = os.environ.get("RAPIDAPI_KEY")
_HOST = os.environ.get("RAPIDAPI_HOST", "annas-archive-api.p.rapidapi.com")
_DL_URL = "https://annas-archive-api.p.rapidapi.com/download"
_session = None


async def _get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=900)
        )
    return _session


@router.get("/annas")
async def download_annas(md5: str):
    if not _KEY:
        raise HTTPException(
            status_code=503, detail="RAPIDAPI_KEY not configured"
        )
    if not md5 or len(md5) != 32:
        raise HTTPException(status_code=400, detail="invalid md5")
    session = await _get_session()
    try:
        resp = await session.get(
            _DL_URL,
            params={"md5": md5},
            headers={
                "x-rapidapi-key": _KEY,
                "x-rapidapi-host": _HOST,
            },
        )
    except Exception:
        raise HTTPException(status_code=502, detail="upstream request failed")
    if resp.status >= 400:
        await resp.release()
        raise HTTPException(status_code=502, detail="upstream download failed")
    headers = {
        "Content-Type": resp.headers.get(
            "Content-Type", "application/octet-stream"
        )
    }
    cd = resp.headers.get("Content-Disposition")
    if cd:
        headers["Content-Disposition"] = cd
    return StreamingResponse(
        resp.content,
        status_code=resp.status,
        headers=headers,
        background=resp.release,
    )
