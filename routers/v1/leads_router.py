import csv
import io

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from torrents.indiamart import IndiaMart
from torrents.justdial import JustDial

router = APIRouter(tags=["Leads"])

LEADS_SITES = {
    "indiamart": IndiaMart,
    "justdial": JustDial,
}

CSV_HEADERS = [
    "Business Name", "Phone", "Phone 2", "GSTIN", "GST (Masked)",
    "GST Verified", "City", "Business Type", "Rating", "Reviews",
    "Member Since", "URL",
]


async def _collect(site, query, url, limit, city=""):
    scraper = LEADS_SITES[site]()
    return await scraper.search(query, 1, limit, url=url, city=city)


def _row_values(r):
    phones = r.get("phones") or []
    return [
        r.get("name") or "",
        r.get("phone") or "",
        phones[1] if len(phones) > 1 else "",
        r.get("gst") or "",
        r.get("gst_masked") or "",
        "Yes" if r.get("gst_verified") else "",
        r.get("city") or "",
        r.get("business_type") or "",
        r.get("rating") or "",
        r.get("reviews") or "",
        r.get("member_since") or "",
        r.get("url") or "",
    ]


def _csv_response(resp, site, query):
    rows = resp.get("data") or []
    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM so Excel opens Hindi/unicode names correctly
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADERS)
    for r in rows:
        writer.writerow(_row_values(r))
    fname = "leads_{}_{}.csv".format(site, (query or "export")[:40].replace(" ", "_").replace("/", "_"))
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="{}"'.format(fname)},
    )


@router.get("/leads")
async def get_leads(
    site: str = Query("indiamart", description="indiamart | justdial"),
    query: str = Query("", description="business keyword, e.g. kitchen chimney"),
    url: str = Query("", description="optional full indiamart/justdial search or company URL"),
    limit: int = Query(10, ge=1, le=30),
    gst_only: int = Query(0, description="1 = drop rows without any GST info"),
    city: str = Query("", description="justdial: city name, e.g. Delhi (optional if url given)"),
):
    site = site.lower().strip()
    if site not in LEADS_SITES:
        return {"error": "Unknown lead site '{}'. Use indiamart or justdial.".format(site)}
    if not query and not url:
        return {"error": "Send a query (e.g. query=kitchen chimney) or a full site url."}
    try:
        resp = await _collect(site, query, url, limit, city)
    except Exception as e:
        return {"error": str(e)}
    if gst_only:
        resp["data"] = [r for r in (resp.get("data") or []) if r.get("gst") or r.get("gst_masked")]
        resp["total"] = len(resp["data"])
    resp["site"] = site
    return resp


@router.get("/leads/export")
async def export_leads(
    site: str = Query("indiamart"),
    query: str = Query(""),
    url: str = Query(""),
    limit: int = Query(10, ge=1, le=30),
    city: str = Query(""),
):
    site = site.lower().strip()
    if site not in LEADS_SITES:
        return {"error": "Unknown lead site '{}'.".format(site)}
    if not query and not url:
        return {"error": "Send a query or url."}
    try:
        resp = await _collect(site, query, url, limit, city)
    except Exception as e:
        return {"error": str(e)}
    return _csv_response(resp, site, query)
