import subprocess
import os
import time

_start_time = time.time()
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COMMIT_INFO = os.path.join(_REPO, "COMMIT_INFO")


def _git_info():
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO, stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=_REPO, stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        ts = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%ci"],
            cwd=_REPO, stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        info = {"commit": commit, "last_commit": msg, "commit_date": ts}
        # Write to disk so it survives git-less environments
        try:
            with open(_COMMIT_INFO, "w") as f:
                f.write(f"{commit}\n{msg}\n{ts}")
        except Exception:
            pass
        return info
    except Exception:
        pass
    # Fallback: read from COMMIT_INFO file
    try:
        if os.path.exists(_COMMIT_INFO):
            with open(_COMMIT_INFO) as f:
                lines = f.read().strip().split("\n", 2)
            return {
                "commit": lines[0] if lines else "unknown",
                "last_commit": lines[1] if len(lines) > 1 else "",
                "commit_date": lines[2] if len(lines) > 2 else "",
            }
    except Exception:
        pass
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
