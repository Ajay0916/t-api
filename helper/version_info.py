import subprocess
import os
import time

_start_time = time.time()

def _git_info():
    try:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
        return {"commit": commit, "last_commit": msg, "commit_date": ts}
    except Exception:
        return {"commit": "unknown", "last_commit": "", "commit_date": ""}


def get_version_info():
    uptime = int(time.time() - _start_time)
    hours, rem = divmod(uptime, 3600)
    mins, secs = divmod(rem, 60)
    git = _git_info()
    return {
        "api_version": "v1.6.10",
        "commit": git["commit"],
        "last_commit": git["last_commit"],
        "commit_date": git["commit_date"],
        "uptime": f"{hours}h{mins}m{secs}s",
    }
