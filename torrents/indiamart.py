import asyncio
import re
import time
from urllib.parse import quote

from helper.leads import (
    GST_MASK_RE,
    GSTIN_RE,
    extract_phones,
    gstin_valid,
    jina_fetch,
    mask_matches,
    wayback_fetch,
)


def _clean_slug(slug):
    return re.sub(r"[^a-z0-9-]", "", (slug or "").lower())


class IndiaMart:
    _name = "IndiaMART"

    def __init__(self):
        self.sem = asyncio.Semaphore(3)

    async def _profile(self, slug):
        """Live company profile -> name / masked GST / phone / details."""
        html = await jina_fetch("https://www.indiamart.com/{}/".format(slug))
        if not html:
            return None
        row = {"slug": slug, "url": "https://www.indiamart.com/{}/".format(slug)}
        m = re.search(r'"companyName":"([^"]*)"', html)
        if m:
            row["name"] = m.group(1)
        m = re.search(r"<h1[^>]*>\s*([^<]{2,80})", html)
        if not row.get("name") and m:
            row["name"] = m.group(1).strip()
        m = re.search(r"<title>([^<]*)", html)
        if m:
            t = re.match(r"^(?P<name>.+?),(?P<city>[^-]{1,60}?)\s*-\s*(?P<type>.{2,80})$", m.group(1).strip())
            if t:
                row.setdefault("name", t.group("name").strip())
                row["city"] = t.group("city").strip()
                row.setdefault("business_type", t.group("type").strip())
        m = re.search(r'"businessType":"([^"]*)"', html)
        if m:
            row["business_type"] = m.group(1)
        m = re.search(r'"seller_rating":"([^"]*)"', html)
        if m:
            try:
                row["rating"] = float(m.group(1))
            except ValueError:
                pass
        m = re.search(r'"rating_count":"([^"]*)"', html)
        if m:
            row["reviews"] = m.group(1)
        m = re.search(r'"membersince":"([^"]*)"', html)
        if m:
            row["member_since"] = m.group(1)
        m = GST_MASK_RE.search(html)
        if m:
            row["gst_masked"] = m.group(0)
        phones = extract_phones(html)
        if phones:
            row["phone"] = phones[0]
            if len(phones) > 1:
                row["phones"] = phones
        if re.search(r"GST Verified|gst_verified_flag[\"']?\s*[:=]\s*1", html):
            row["gst_verified"] = True
        return row

    async def _company(self, slug):
        async with self.sem:
            row, body = await asyncio.gather(
                self._profile(slug), wayback_fetch("www.indiamart.com/{}/".format(slug))
            )
            if not row:
                return None
            if body:
                masked = row.get("gst_masked")
                for g in GSTIN_RE.findall(body):
                    if mask_matches(masked, g) and gstin_valid(g):
                        row["gst"] = g
                        break
                if not row.get("gst") and not masked:
                    m = GSTIN_RE.search(body)
                    if m and gstin_valid(m.group(0)):
                        row["gst"] = m.group(0)
            if row.get("gst"):
                row["gst_valid"] = True
            elif row.get("gst_masked"):
                row["gst_valid"] = False
            row["site"] = "indiamart"
            row["category"] = "Lead"
            return row

    async def search(self, query, page=1, limit=10, url=None):
        start = time.time()
        limit = max(1, min(int(limit or 10), 30))
        if url and "indiamart.com" in url:
            search_url = url
            m = re.search(r"[?&]ss=([^&]+)", url)
            query = m.group(1).replace("+", " ") if m else query
        else:
            search_url = "https://dir.indiamart.com/search.mp?ss={}".format(quote(query or ""))
        html = await jina_fetch(search_url)
        if not html:
            return {"data": [], "error": "IndiaMART search blocked right now (reader proxy failed). Try again in a minute.", "time": time.time() - start, "total": 0}
        slugs = []
        for m in re.finditer(r'href="/company/([a-z0-9-]+)/[^"]*"[^>]*>([^<]{2,80})<', html):
            slug = _clean_slug(m.group(1))
            if slug and slug not in slugs:
                slugs.append((slug, m.group(2).strip()))
        if not slugs:
            return {"data": [], "error": "No businesses found for this query.", "time": time.time() - start, "total": 0}
        rows = []
        for slug, name in slugs[:limit]:
            row = await self._company(slug)
            if not row:
                continue
            row.setdefault("name", name)
            rows.append(row)
            if len(rows) >= limit:
                break
        return {
            "data": rows,
            "current_page": page,
            "total_pages": 1,
            "total": len(rows),
            "time": time.time() - start,
            "query": query,
        }
