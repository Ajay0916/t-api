#!/bin/bash
# Auto-update t-api on startup (like Vj-wz update.py)
set -e
cd "$(dirname "$0")"

echo "[STARTUP] Auto-updating..."
if [ -d ".git" ]; then
    git fetch origin -q 2>/dev/null || true
    git reset --hard origin/main -q 2>/dev/null || true
    git pull --ff-only -q 2>/dev/null || true
fi

# Write COMMIT_INFO
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
MSG=$(git log -1 --pretty=%s 2>/dev/null || echo "")
DATE=$(git log -1 --pretty=%ci 2>/dev/null || echo "")
echo -e "${COMMIT}\n${MSG}\n${DATE}" > COMMIT_INFO 2>/dev/null || true

echo "[STARTUP] Commit: $COMMIT"
exec python main.py "$@"
