"""Mirror fallback utility for torrent sites.

If the primary site is down, try mirror domains automatically.
Each site defines its own MIRRORS list in constants/base_url.py.
"""


async def search_with_mirrors(site_obj, query, page, limit, mirrors, search_fn):
    """Try primary URL first, then mirrors if no results.
    
    Args:
        site_obj: Instance of the site class (has BASE_URL attribute)
        query: Search query string
        page: Page number
        limit: Results limit
        mirrors: List of mirror URLs
        search_fn: Async function(site_obj, query, page, limit) -> result dict
    """
    # Try primary
    result = await search_fn(site_obj, query, page, limit)
    if result and result.get("data"):
        return result
    
    # Try mirrors
    original_base = site_obj.BASE_URL
    for mirror in mirrors:
        if mirror == original_base:
            continue
        try:
            site_obj.BASE_URL = mirror
            result = await search_fn(site_obj, query, page, limit)
            if result and result.get("data"):
                return result
        except Exception:
            continue
        finally:
            site_obj.BASE_URL = original_base
    
    return result
