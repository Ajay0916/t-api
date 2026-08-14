import aiohttp

HEADER_AIO = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
}

# TorrentGalaxy's search API needs its Cloudflare fence_key cookie; sending
# it to every site breaks others (magnetdl drops the connection), so it stays
# scoped to TGX only.
HEADER_TGX = {
    **HEADER_AIO,
    "Cookie": "fencekey=0e31613a539b90e445bbcecafaa5a273",
}


AIO_TIMEOUT = aiohttp.ClientTimeout(total=10)
