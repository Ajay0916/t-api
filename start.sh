#!/bin/bash
cd "$(dirname "$0")"

echo "[STARTUP] Starting Torrents-Api..."

# Write COMMIT_INFO (read only, don't modify git)
if [ -d ".git" ]; then
    COMMIT=$(git -c safe.directory='*' rev-parse --short HEAD 2>/dev/null || echo "unknown")
    MSG=$(git -c safe.directory='*' log -1 --pretty=%s 2>/dev/null || echo "")
    DATE=$(git -c safe.directory='*' log -1 --pretty=%ci 2>/dev/null || echo "")
else
    COMMIT="unknown"
    MSG=""
    DATE=""
fi
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
