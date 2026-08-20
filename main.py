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
    version="1.6.12",
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

    Vj-wz update.py approach:
    1. rm -rf .git  (destroy broken state - branch mismatches etc)
    2. git init → git add . → git commit  (snapshot current code)
    3. git remote add origin → git fetch → git reset --hard origin/main
    4. os._exit(0)  →  systemd Restart=always picks up new code

    Uses asyncio.create_subprocess_exec (like Vj-wz cmd_exec) so
    git operations complete BEFORE we exit.
    """
    import asyncio, os, threading, time as _time

    repo = os.path.dirname(os.path.abspath(__file__))
    upstream = "https://github.com/Ajay0916/t-api.git"
    branch = "main"
    env = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}

    async def _run(cmd, timeout=60):
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=repo, env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()

    # Vj-wz _run_update: destroy .git, reinit, fresh fetch
    if os.path.isdir(os.path.join(repo, ".git")):
        await _run(["rm", "-rf", ".git"])

    # No git add/commit — just init, fetch, reset (avoids huge venv commit)
    await _run(["git", "init", "-q"])
    await _run(["git", "remote", "add", "origin", upstream])
    await _run(["git", "fetch", "origin", "-q"])
    await _run(["git", "reset", "--hard", f"origin/{branch}", "-q"])

    # Write COMMIT_INFO
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "--short", "HEAD",
        cwd=repo, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    commit = stdout.decode().strip() if stdout else "unknown"

    proc = await asyncio.create_subprocess_exec(
        "git", "log", "-1", "--pretty=%s",
        cwd=repo, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    msg = stdout.decode().strip() if stdout else ""

    proc = await asyncio.create_subprocess_exec(
        "git", "log", "-1", "--pretty=%ci",
        cwd=repo, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    date = stdout.decode().strip() if stdout else ""

    try:
        with open(os.path.join(repo, "COMMIT_INFO"), "w") as f:
            f.write(f"{commit}\n{msg}\n{date}")
    except Exception:
        pass

    # Exit - systemd Restart=always restarts with new code
    threading.Thread(target=lambda: (_time.sleep(1), os._exit(0)), daemon=True).start()
    return {"status": "restarting", "message": f"Updated to {commit}. Restarting..."}

handler = Mangum(app)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8009, loop="asyncio")
