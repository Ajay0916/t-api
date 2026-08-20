#!/bin/bash
cd "$(dirname "$0")"

UPSTREAM="https://github.com/Ajay0916/t-api.git"
BRANCH="main"

echo "[STARTUP] Auto-updating..."

# Vj-wz style: destroy .git, fresh init, fetch, reset
# Use -c safe.directory='*' to bypass dubious ownership check
rm -rf .git 2>/dev/null || true
git -c safe.directory='*' init -q 2>/dev/null || true
git -c safe.directory='*' remote add origin "$UPSTREAM" 2>/dev/null || true
git -c safe.directory='*' fetch origin -q 2>/dev/null || true
git -c safe.directory='*' reset --hard "origin/$BRANCH" -q 2>/dev/null || true

# Write COMMIT_INFO
COMMIT=$(git -c safe.directory='*' rev-parse --short HEAD 2>/dev/null || echo "unknown")
MSG=$(git -c safe.directory='*' log -1 --pretty=%s 2>/dev/null || echo "")
DATE=$(git -c safe.directory='*' log -1 --pretty=%ci 2>/dev/null || echo "")
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
