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


async def sweep_flare_sessions(flare_url="http://127.0.0.1:8191"):
    """Destroy every Flaresolverr session (run at API startup).

    t-api is restarted with pkill -9, which orphans the sessions of the
    killed process - each one keeps a headless Chromium alive on the
    Flaresolverr host. Over restarts they pile up and starve the host, so
    challenge solves crawl (search deadlines hit, enrichment magnets are
    skipped, dl.php falls back to slow browser fetches). On boot the new
    process owns no sessions yet, so destroying all of them is safe.
    """
    flare_url = (flare_url or "http://127.0.0.1:8191").rstrip("/")
    try:
        async with aiohttp.ClientSession() as client:
            async with client.post(
                "{}/v1".format(flare_url),
                json={"cmd": "sessions.list"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as res:
                data = await res.json(content_type=None)
        reserved = {"downloadly_persistent"}
        for sid in data.get("sessions") or []:
            if isinstance(sid, str) and sid and sid not in reserved:
                await close_flare_session(sid, flare_url)
    except Exception:
        pass


def sweep_flare_sessions_async(flare_url="http://127.0.0.1:8191"):
    """Fire-and-forget startup sweep; never blocks or crashes boot."""
    try:
        asyncio.get_running_loop().create_task(
            sweep_flare_sessions(flare_url)
        )
    except RuntimeError:
        pass
