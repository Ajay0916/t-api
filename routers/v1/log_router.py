"""Vj-wz style log viewer endpoint.

GET /api/v1/log?lines=50&format=text    → Plain text (Vj-wz bot format)
GET /api/v1/log?lines=50&format=json    → JSON with metadata
GET /api/v1/log?format=tail             → Last N lines only (raw)
"""
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse, JSONResponse

router = APIRouter(tags=["Log"])

LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "log.txt",
)


def _read_log(max_lines=50):
    """Read last N lines from log.txt (Vj-wz style)."""
    if not os.path.exists(LOG_FILE):
        return [], 0
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return all_lines[-max_lines:], len(all_lines)
    except Exception:
        return [], 0


@router.get("")
async def get_log(
    lines: int = Query(50, ge=1, le=500),
    format: str = Query("text", regex="^(text|json|tail)$"),
):
    log_lines, total = _read_log(lines)

    if format == "tail":
        return PlainTextResponse("".join(log_lines))

    if format == "json":
        return JSONResponse({
            "total_lines": total,
            "returned_lines": len(log_lines),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "logs": [line.rstrip("\n") for line in log_lines],
        })

    # Vj-wz style formatted text (for Telegram display)
    cleaned = []
    for line in log_lines:
        parts = line.split("] [", 1)
        cleaned.append(f"[{parts[1]}" if len(parts) > 1 else line.rstrip())

    text = (
        f"<b>t-api Log</b> ({len(cleaned)}/{total} lines)\n"
        f"----------<b>START LOG</b>----------\n\n"
        f"<code>{''.join(cleaned)}</code>\n"
        f"----------<b>END LOG</b>----------"
    )
    return PlainTextResponse(text, media_type="text/plain")
