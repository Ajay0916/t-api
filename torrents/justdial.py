import re
import time
from urllib.parse import quote

from helper.leads import GSTIN_RE, extract_phones, jina_fetch, wayback_fetch
from helper.plain_curl import fetch_plain


class JustDial:
    _name = "JustDial"

    async def _fetch(self, url):
        """Layered fetch: plain curl -> jina reader -> wayback snapshot.
        JustDial sits behind Akamai and usually denies datacenter IPs on the
        live layers; the wayback layer still serves archived listing pages."""
        body = await fetch_plain(url, timeout=10)
        if body and len(body) > 500 and "Access Denied" not in body:
            return body, "direct"
        body = await jina_fetch(url)
        if body and "Access Denied" not in body and len(body) > 500:
            return body, "jina"
        body = await wayback_fetch(url)
        if body:
            return body, "wayback"
        return None, None

    @staticmethod
    def _rows(html):
        """Listing rows from a JustDial results page: business name + href.
        Phone numbers live behind Akamai/click-reveal, so they are picked
        from whatever the served HTML exposes (data-phone / callNumber /
        tel: / plain 10-digit numbers)."""
        rows, seen = [], set()
        for m in re.finditer(r'<a[^>]*href="(https://www\.justdial\.com/[^"?#]+)"[^>]*>(.*?)</a>', html, re.S):
            href, anchor = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
            name = re.sub(r"\s+", " ", anchor).strip()
            low = name.lower()
            if (not name or len(name) > 100 or "explore" in low
                    or "/cms/" in href or "/login" in href or "/register" in href
                    or low.startswith(("justdial", "call", "view", "login", "sign", "we are",
                                       "all", "read", "track", "get", "book", "download",
                                       "career", "investor", "blog", "sitemap", "about",
                                       "contact", "privacy", "terms", "help", "faq"))):
                continue
            key = low[:40]
            if key in seen:
                continue
            seen.add(key)
            row = {"name": name, "url": href, "site": "justdial"}
            m2 = re.search(r"(?<!\d)([6-9][0-9]{9})(?!\d)", href)
            if m2:
                row["phone"] = m2.group(1)
            rows.append(row)
        return rows

    async def search(self, query, page=1, limit=10, url=None, city=""):
        start = time.time()
        limit = max(1, min(int(limit or 10), 30))
        if url and "justdial.com" in url:
            search_url = url
        elif city:
            keyword = "-".join(str(query or "").strip().lower().split())
            search_url = "https://www.justdial.com/{}/{}".format(quote(city.strip()), quote(keyword))
        else:
            search_url = "https://www.justdial.com/search?q={}".format(quote(query or ""))
        body, layer = await self._fetch(search_url)
        if not body:
            return {"data": [], "error": "JustDial is blocked from this server's IP (Akamai). Add a residential HTTP_PROXY to reach it, or retry later.", "time": time.time() - start, "total": 0}
        rows = self._rows(body)
        if not rows:
            return {"data": [], "error": "JustDial page loaded but no businesses parsed (likely a block/captcha page).", "time": time.time() - start, "total": 0}
        rows = rows[:limit]
        gst = GSTIN_RE.findall(body)
        for r in rows:
            phones = extract_phones(body)
            r.setdefault("phone", phones[0] if phones else None)
            r["gst"] = gst[0] if gst else None
            r["gst_valid"] = bool(r.get("gst"))
            r["category"] = "Lead"
        return {"data": rows, "current_page": page, "total_pages": 1, "total": len(rows), "time": time.time() - start, "query": query, "layer": layer}
