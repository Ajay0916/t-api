"""Log viewer endpoint — Vj-wz style /log command.

GET /api/v1/log?key=5963
  → Returns last N lines from /tmp/dl_resolve.log + recent stdout.
"""
import os
from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["Log"])


@router.get("")
async def get_log(lines: int = Query(30, description="Number of lines")):
    logs = []

    # 1. downloadly resolve debug log
    dl_log = "/tmp/dl_resolve.log"
    if os.path.exists(dl_log):
        try:
            with open(dl_log) as f:
                all_lines = f.readlines()
            logs.append(f"=== dl_resolve.log (last {min(lines, len(all_lines))}) ===")
            logs.extend(all_lines[-lines:])
        except Exception as e:
            logs.append(f"=== dl_resolve.log error: {e} ===")

    # 2. Check if curl is accessible
    import subprocess
    try:
        r = subprocess.run(["/usr/bin/curl", "--version"], capture_output=True, timeout=3)
        logs.append(f"\n=== curl version ===")
        logs.append(r.stdout.decode().split("\n")[0])
    except Exception as e:
        logs.append(f"\n=== curl error: {e} ===")

    # 3. Test bare curl to downloadly
    try:
        r = subprocess.run(
            ["/usr/bin/curl", "-sL", "-4", "--max-time", "10", "--",
             "https://downloadlynet.ir/"],
            capture_output=True, timeout=15
        )
        logs.append(f"\n=== test curl downloadlynet.ir ===")
        logs.append(f"rc={r.returncode} stdout_len={len(r.stdout)} stderr={r.stderr[:200].decode(errors='replace')}")
    except Exception as e:
        logs.append(f"\n=== test curl error: {e} ===")

    # 4. Check process info
    logs.append(f"\n=== process info ===")
    logs.append(f"pid={os.getpid()} cwd={os.getcwd()}")

    return PlainTextResponse("\n".join(logs))
