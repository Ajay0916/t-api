import asyncio

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


async def fetch_plain(url, timeout=12):
    """Fetch a page with the system curl binary.

    Cloudflare serves plain curl (no cookies, no JS) on magnetdl/freecourseweb
    while challenging or blackholing impersonated TLS clients, so the plain
    curl path is the primary fetcher for those sites. IPv4 is forced because
    the sites publish AAAA records and this host's v6 routing is broken (v6
    attempts hang until timeout).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl",
            "-sL",
            "-4",
            "--compressed",
            "-A",
            CHROME_UA,
            "--max-time",
            str(timeout),
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except Exception:
        return None
    if proc.returncode != 0 or not out:
        return None
    return out.decode("utf-8", errors="replace")
