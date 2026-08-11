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
