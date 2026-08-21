import asyncio

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

CF_CHALLENGE_MARKERS = (
    "cf-chl",
    "challenge-platform",
    "cf-browser-verification",
    "just a moment",
)


def _is_cf_challenge(html):
    low = html.lower()
    return any(m in low for m in CF_CHALLENGE_MARKERS)


async def _curl(args, timeout, family="-4"):
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl",
            "-sL",
            family,
            "-A",
            CHROME_UA,
            "-w",
            "\n%{http_code}",
            "--max-time",
            str(timeout),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except Exception:
        return None
    if proc.returncode != 0 or not out:
        return None
    body, _, code = out.rpartition(b"\n")
    try:
        code = int(code)
    except ValueError:
        return None
    if code != 200:
        return None
    return body.decode("utf-8", errors="replace")


async def fetch_plain(url, timeout=8, family=None):
    """Fetch a page with the system curl binary.

    Cloudflare serves plain curl (no cookies, no JS) on magnetdl/freecourseweb
    while challenging or blackholing impersonated TLS clients, so the plain
    curl path is the primary fetcher for those sites. IPv4 is tried first,
    then IPv6: the VPS has working IPv6 now and several CF-fronted hosts
    (torlock/freecourseweb) serve real pages over v6 while blackholing or
    stripping v4. Only HTTP 200 bodies count as success so the
    caller's fallback chain engages on challenges/blocks.
    """
    if family == 4:
        return await _curl([url], timeout, "-4")
    if family == 6:
        return await _curl([url], timeout, "-6")
    body = await _curl([url], timeout, "-4")
    if body:
        return body
    return await _curl([url], timeout, "-6")


async def fetch_jina(url, timeout=12):
    """Fetch a page through the r.jina.ai reader proxy.

    magnetdl intermittently blackholes this host's IP at the TCP level (even
    plain curl gets 000) and challenges jina's upstream too, but jina flaps
    between real pages and challenge pages, so a second attempt is made when
    the first one comes back as a Cloudflare challenge. jina returns the page
    HTML unchanged when asked with X-Return-Format: html, so the existing
    parsers work as-is.
    """
    body = await _curl(
        ["-H", "X-Return-Format: html", "https://r.jina.ai/" + url], timeout
    )
    if body and not _is_cf_challenge(body):
        return body
    body = await _curl(
        ["-H", "X-Return-Format: html", "https://r.jina.ai/" + url], timeout
    )
    if body and not _is_cf_challenge(body):
        return body
    return None
