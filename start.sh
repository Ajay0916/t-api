#!/bin/bash
# Auto-update t-api on startup (Vj-wz update.py style)
set -e
cd "$(dirname "$0")"

UPSTREAM="https://github.com/Ajay0916/t-api.git"
BRANCH="main"

echo "[STARTUP] Auto-updating..."

# Vj-wz approach: destroy .git, reinit, fresh fetch (always works)
if [ -d ".git" ]; then
    rm -rf .git
fi

git init -q 2>/dev/null || true
git add . 2>/dev/null || true
git commit -sm "update" -q 2>/dev/null || true
git remote add origin "$UPSTREAM" 2>/dev/null || git remote set-url origin "$UPSTREAM" 2>/dev/null
git fetch origin -q 2>/dev/null || true
git reset --hard "origin/$BRANCH" -q 2>/dev/null || true

# Write COMMIT_INFO
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
