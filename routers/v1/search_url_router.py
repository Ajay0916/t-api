from helper.result_cleaner import clean_results
from fastapi import APIRouter, status
from helper.is_site_available import check_if_site_available
from helper.error_messages import error_handler

router = APIRouter(tags=["Torrent By Url"])


@router.get("/")
@router.get("")
async def get_torrent_from_url(site: str, url: str):
    site = site.lower()
    all_sites = check_if_site_available(site)
    if not all_sites:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Selected Site Not Available"},
        )
    fetcher = getattr(all_sites[site]["website"](), "get_torrent_by_url", None)
    if fetcher is None:
        return error_handler(
            status_code=status.HTTP_400_BAD_REQUEST,
            json_message={
                "error": "Torrent-by-URL is not supported for {}.".format(site)
            },
        )
    try:
        resp = await fetcher(url)
    except Exception:
        return error_handler(
            status_code=status.HTTP_502_BAD_GATEWAY,
            json_message={"error": "Failed to fetch torrent page."},
        )
    if resp is None:
        return error_handler(
            status_code=status.HTTP_403_FORBIDDEN,
            json_message={"error": "Website Blocked Change IP or Website Domain."},
        )
    elif len(resp["data"]) > 0:
        return clean_results(resp)
    else:
        return error_handler(
            status_code=status.HTTP_404_NOT_FOUND,
            json_message={"error": "Result not found."},
        )
