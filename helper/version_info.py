import subprocess
import os
import time

_start_time = time.time()
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COMMIT_INFO = os.path.join(_REPO, "COMMIT_INFO")
_ENV = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}


def _run_git(args):
    for git_bin in ["/usr/bin/git", "/usr/local/bin/git", "/snap/bin/git", "git"]:
        try:
            return subprocess.check_output(
                [git_bin, "-c", "safe.directory=*"] + args,
                cwd=_REPO, stderr=subprocess.DEVNULL, timeout=5, env=_ENV
            ).decode().strip()
        except Exception:
            continue
    return None


def _read_commit_file():
    """Read COMMIT_INFO file as fallback."""
    try:
        if os.path.exists(_COMMIT_INFO):
            with open(_COMMIT_INFO) as f:
                lines = f.read().strip().split("\n", 2)
            if lines and lines[0] and lines[0] != "unknown":
                return {
                    "commit": lines[0],
                    "last_commit": lines[1] if len(lines) > 1 else "",
                    "commit_date": lines[2] if len(lines) > 2 else "",
                }
    except Exception:
        pass
    return None


def _git_info():
    # Try COMMIT_INFO file first (written by start.sh on startup)
    file_info = _read_commit_file()
    if file_info:
        # Also try git to update the file if possible
        commit = _run_git(["rev-parse", "--short", "HEAD"])
        if commit:
            msg = _run_git(["log", "-1", "--pretty=%s"]) or ""
            ts = _run_git(["log", "-1", "--pretty=%ci"]) or ""
            try:
                with open(_COMMIT_INFO, "w") as f:
                    f.write(f"{commit}\n{msg}\n{ts}")
            except Exception:
                pass
            return {"commit": commit, "last_commit": msg, "commit_date": ts}
        return file_info
    # Try git directly
    commit = _run_git(["rev-parse", "--short", "HEAD"])
    if commit:
        msg = _run_git(["log", "-1", "--pretty=%s"]) or ""
        ts = _run_git(["log", "-1", "--pretty=%ci"]) or ""
        try:
            with open(_COMMIT_INFO, "w") as f:
                f.write(f"{commit}\n{msg}\n{ts}")
        except Exception:
            pass
        return {"commit": commit, "last_commit": msg, "commit_date": ts}
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
