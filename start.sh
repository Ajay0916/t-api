#!/bin/bash
# Auto-update t-api on startup (like Vj-wz update.py)
set -e
cd "$(dirname "$0")"

echo "[STARTUP] Auto-updating..."
if [ -d ".git" ]; then
    /usr/bin/git fetch origin -q 2>/dev/null || true
    /usr/bin/git reset --hard origin/main -q 2>/dev/null || true
    /usr/bin/git pull --ff-only -q 2>/dev/null || true
fi

# Write COMMIT_INFO
COMMIT=$(/usr/bin/git rev-parse --short HEAD 2>/dev/null || echo "unknown")
MSG=$(/usr/bin/git log -1 --pretty=%s 2>/dev/null || echo "")
DATE=$(/usr/bin/git log -1 --pretty=%ci 2>/dev/null || echo "")
echo -e "${COMMIT}\n${MSG}\n${DATE}" > COMMIT_INFO 2>/dev/null || true

echo "[STARTUP] Commit: $COMMIT"
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
fi
if command -v python3 &>/dev/null; then
    exec python3 main.py "$@"
elif command -v python &>/dev/null; then
    exec python main.py "$@"
else
    echo "[STARTUP] ERROR: python not found"
    exit 1
fi
