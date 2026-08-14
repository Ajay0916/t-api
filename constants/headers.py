import aiohttp

HEADER_AIO = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Shared Cloudflare fence_key: aiohttp's TLS fingerprint gets challenged
    # by several sites (tgx, freecourseweb) unless a valid fence_key cookie
    # rides along. magnetdl used to drop connections on it, but magnetdl now
    # fetches through curl_cffi (browser impersonation) which never sends it.
    "Cookie": "fencekey=0e31613a539b90e445bbcecafaa5a273",
}


AIO_TIMEOUT = aiohttp.ClientTimeout(total=10)
