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
    version="1.6.11",
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
    repo = os.path.dirname(os.path.abspath(__file__))
    info_path = os.path.join(repo, "COMMIT_INFO")
    env = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
    for git_bin in ["/usr/bin/git", "/usr/local/bin/git", "git"]:
        try:
            commit = subprocess.check_output(
                [git_bin, "rev-parse", "--short", "HEAD"],
                cwd=repo, stderr=subprocess.DEVNULL, timeout=3, env=env
            ).decode().strip()
            msg = subprocess.check_output(
                [git_bin, "log", "-1", "--pretty=%s"],
                cwd=repo, stderr=subprocess.DEVNULL, timeout=3, env=env
            ).decode().strip()
            ts = subprocess.check_output(
                [git_bin, "log", "-1", "--pretty=%ci"],
                cwd=repo, stderr=subprocess.DEVNULL, timeout=3, env=env
            ).decode().strip()
            with open(info_path, "w") as f:
                f.write(f"{commit}\n{msg}\n{ts}")
            return
        except Exception:
            continue


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



@app.get("/restart", dependencies=[Depends(authenticate_request)])
async def restart():
    """Pull latest code + restart the service (Vj-wz style).

    1. Write a shell script that does git pull.
    2. Run it detached (start_new_session=True) so it survives our exit.
    3. Return response immediately, then os._exit(0).
    4. systemd Restart=always brings us back with new code.
    """
    import subprocess as _sp, os, threading, time as _time

    repo = os.path.dirname(os.path.abspath(__file__))
    env = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
    upstream = "https://github.com/Ajay0916/t-api.git"

    script_content = "#!/bin/bash\n"
    script_content += "sleep 2\n"
    script_content += "cd '" + repo + "'\n"
    script_content += "/usr/bin/git remote set-url origin '" + upstream + "' 2>/dev/null || "
    script_content += "/usr/bin/git remote add origin '" + upstream + "' 2>/dev/null\n"
    script_content += "/usr/bin/git fetch origin -q 2>/dev/null\n"
    script_content += "/usr/bin/git reset --hard origin/main -q 2>/dev/null\n"
    script_content += 'COMMIT=$(/usr/bin/git rev-parse --short HEAD 2>/dev/null || echo unknown)\n'
    script_content += "MSG=$(/usr/bin/git log -1 --pretty=%s 2>/dev/null || echo '')\n"
    script_content += "DATE=$(/usr/bin/git log -1 --pretty=%ci 2>/dev/null || echo '')\n"
    script_content += "printf '%s\\n%s\\n%s\\n' \"$COMMIT\" \"$MSG\" \"$DATE\" > '" + repo + "/COMMIT_INFO' 2>/dev/null\n"
    script_content += "/usr/bin/systemctl restart t-api 2>/dev/null\n"

    script_path = os.path.join("/tmp", "tapi_restart.sh")
    with open(script_path, "w") as f:
        f.write(script_content)
    os.chmod(script_path, 0o755)

    # Detached subprocess — survives parent death (like Vj-wz cmd_exec)
    _sp.Popen(
        ["/bin/bash", script_path],
        start_new_session=True,
        stdout=_sp.DEVNULL,
        stderr=_sp.DEVNULL,
        env=env,
    )

    # Fallback: if systemctl restart doesn't fire in 5s, force exit
    def _fallback_exit():
        _time.sleep(5)
        os._exit(0)
    threading.Thread(target=_fallback_exit, daemon=True).start()

    return {"status": "restarting", "message": "Pulling latest code and restarting..."}

handler = Mangum(app)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8009, loop="asyncio")
