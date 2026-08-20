#!/bin/bash
cd "$(dirname "$0")"

UPSTREAM="https://github.com/Ajay0916/t-api.git"
BRANCH="main"

# Fix git dubious ownership
git config --global --add safe.directory "$(pwd)" 2>/dev/null || true

echo "[STARTUP] Auto-updating..."

rm -rf .git 2>/dev/null || true
git init -q 2>&1
echo "[STARTUP] remote: $(git remote add origin "$UPSTREAM" 2>&1 || true)"
echo "[STARTUP] fetch rc=$(git fetch origin 2>&1 | tee /dev/stderr | wc -c)"
echo "[STARTUP] reset rc=$(git reset --hard "origin/$BRANCH" 2>&1 | tee /dev/stderr | wc -c)"

COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
MSG=$(git log -1 --pretty=%s 2>/dev/null || echo "")
DATE=$(git log -1 --pretty=%ci 2>/dev/null || echo "")
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
