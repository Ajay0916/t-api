import asyncio

import aiohttp

_connector = None


def get_connector():
    """Return a shared TCPConnector (created lazily inside a running loop).

    The pool survives across requests so TLS handshakes, DNS lookups and
    connections are reused between searches. SSL verification is disabled
    for speed (same trade-off as most scrapers).
    """
    global _connector
    if _connector is None or _connector.closed:
        _connector = aiohttp.TCPConnector(
            ssl=False,
            limit=100,
            limit_per_host=20,
            enable_cleanup_closed=True,
            ttl_dns_cache=300,
        )
    return _connector


async def close_flare_session(sid, flare_url="http://127.0.0.1:8191"):
    """Destroy a Flaresolverr session so its headless browser is closed.

    t-api reuses one warm session per site and rotates it on a TTL; without
    an explicit destroy the old session's browser+chromedriver stays alive on
    the Flaresolverr host forever and leaks memory/CPU. Flaresolverr 3.5.0
    has no DELETE /v1 route - sessions are destroyed via POST /v1."""
    if not sid:
        return
    try:
        async with aiohttp.ClientSession() as client:
            await client.post(
                "{}/v1".format((flare_url or "").rstrip("/")),
                json={"cmd": "sessions.destroy", "session": sid},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        pass


def close_flare_session_async(sid, flare_url="http://127.0.0.1:8191"):
    """Fire-and-forget variant for sync rotation helpers."""
    if not sid:
        return
    try:
        asyncio.get_running_loop().create_task(
            close_flare_session(sid, flare_url)
        )
    except RuntimeError:
        pass
