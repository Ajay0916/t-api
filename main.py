import uvicorn
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from routers.v1.search_router import router as search_router
from routers.v1.trending_router import router as trending_router
from routers.v1.catergory_router import router as category_router
from routers.v1.recent_router import router as recent_router
from routers.v1.combo_routers import router as combo_router
from routers.v1.sites_list_router import router as site_list_router
from routers.home_router import router as home_router
from routers.v1.search_url_router import router as search_url_router
from routers.v1.status_router import router as status_router
from routers.v1.torrent_file_router import router as torrent_file_router
from routers.v1.magnet_router import router as magnet_router
from routers.v1.test_router import router as test_router
from helper.is_site_available import all_sites
from helper.uptime import getUptime
from helper.session import sweep_flare_sessions_async
from helper.dependencies import authenticate_request
from mangum import Mangum
from math import ceil
import time

startTime = time.time()

app = FastAPI(
    title="Torrents-Api",
    version="1.6.10",
    description="Unofficial Torrents / Books / Courses API — {} sites, mirror rotation, combo search".format(len(all_sites)),
    docs_url="/docs",
    contact={
        "name": "Ajay",
        "url": "https://github.com/Ajay0916",
    },
)

def _write_commit_info():
    """Write git commit info to COMMIT_INFO on startup (best-effort)."""
    import subprocess, os
    try:
        repo = os.path.dirname(os.path.abspath(__file__))
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo, stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=repo, stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        ts = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%ci"],
            cwd=repo, stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        info_path = os.path.join(repo, "COMMIT_INFO")
        with open(info_path, "w") as f:
            f.write(f"{commit}\n{msg}\n{ts}")
    except Exception:
        pass


_write_commit_info()


@app.on_event("startup")
async def _startup_cleanup():
    # Kill Flaresolverr sessions orphaned by the previous pkill -9 restart;
    # leaked headless browsers make every challenge solve slower over time.
    sweep_flare_sessions_async()


origins = ["*"]

app.add_middleware(GZipMiddleware, minimum_size=1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_route(req: Request):
    """
    Health Route : Returns App details.

    """
    return JSONResponse(
        {
            "app": "Torrents-Api",
            "version": "v" + "1.6.10",
            "ip": req.client.host,
            "uptime": ceil(getUptime(startTime)),
        }
    )


app.include_router(search_router, prefix="/api/v1/search", dependencies=[Depends(authenticate_request)])
app.include_router(trending_router, prefix="/api/v1/trending", dependencies=[Depends(authenticate_request)])
app.include_router(category_router, prefix="/api/v1/category", dependencies=[Depends(authenticate_request)])
app.include_router(recent_router, prefix="/api/v1/recent", dependencies=[Depends(authenticate_request)])
app.include_router(combo_router, prefix="/api/v1/all", dependencies=[Depends(authenticate_request)])
app.include_router(site_list_router, prefix="/api/v1/sites", dependencies=[Depends(authenticate_request)])
app.include_router(search_url_router, prefix="/api/v1/search_url", dependencies=[Depends(authenticate_request)])
app.include_router(status_router, prefix="/api/v1/status", dependencies=[Depends(authenticate_request)])
# torrent_file/magnet stay open so shared short links (Direct Link / Share
# Magnet in the bot) work for anyone who clicks them; the full-URL proxy
# form inside torrent_file_router still requires the PIN.
app.include_router(test_router, prefix="/api/v1/test", dependencies=[Depends(authenticate_request)])
app.include_router(torrent_file_router, prefix="/api/v1/torrent_file")
app.include_router(magnet_router, prefix="/api/v1/magnet")
app.include_router(home_router, prefix="")

handler = Mangum(app)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8009, loop="asyncio")
