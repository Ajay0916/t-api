import asyncio
import base64
import os
import re
import time
import uuid
from urllib.parse import quote, quote_plus, unquote, urlencode, urlsplit

import aiohttp
from bs4 import BeautifulSoup

from helper.session import close_flare_session_async, get_connector

FLARESOLVERR_URL = (os.getenv("FLARESOLVERR_URL") or "http://127.0.0.1:8191").rstrip("/")
FLARESOLVERR_ENRICH = (os.getenv("FLARESOLVERR_ENRICH") or "1").strip().lower() not in ("0", "false", "no")
_RUTRACKER_BASE = "https://rutracker.org"
_RUTRACKER_USER = os.getenv("RUTRACKER_USERNAME", "").strip()
_RUTRACKER_PASS = os.getenv("RUTRACKER_PASSWORD", "").strip()


def _load_cookie():
    # Pre-authenticated session cookie ("bb_session=...; bb_guid=...; ...").
    # RuTracker gates logins behind a captcha from datacenter IPs, so when a
    # cookie is set we skip the login POST entirely and send it with every
    # request. Read from RUTRACKER_COOKIE env or rutracker_cookie.txt (repo
    # root, gitignored) so restarts never lose it.
    cookie = os.getenv("RUTRACKER_COOKIE", "").strip()
    if cookie:
        return cookie
    try:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "rutracker_cookie.txt"
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


_RUTRACKER_COOKIE = _load_cookie()
ENRICH_CAP = 6
# Cyrillic -> Latin fallback so untranslated titles stay readable.
_TRANS_TABLE = str.maketrans({
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "Yo",
    "Ж": "Zh", "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M",
    "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
    "Ф": "F", "Х": "Kh", "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Shch",
    "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "Yu", "Я": "Ya",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})
_TRANS_CACHE = {}
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _transliterate(text):
    return str(text or "").translate(_TRANS_TABLE)


# Common RuTracker forum categories -> English, so the category shown in
# results is readable without spending a translation call (and stays stable).
_RU_CAT_MAP = {
    "программирование": "Programming",
    "книги и журналы": "Books & Magazines",
    "книги": "Books",
    "журналы": "Magazines",
    "учебники": "Textbooks",
    "учебная литература": "Study Literature",
    "научная литература": "Scientific Literature",
    "техническая литература": "Technical Books",
    "художественная литература": "Fiction",
    "фильмы": "Movies",
    "сериалы": "TV Series",
    "мультфильмы": "Cartoons",
    "аниме": "Anime",
    "игры": "Games",
    "музыка": "Music",
    "аудиокниги": "Audiobooks",
    "аудиокнига": "Audiobook",
    "обучающие видео": "Educational Videos",
    "видеоуроки": "Video Tutorials",
    "спорт": "Sports",
    "хобби и ремесла": "Hobbies & Crafts",
    "справочные материалы": "Reference Materials",
    "документалистика": "Documentaries",
    "софт": "Software",
    "программы": "Software",
    "мобильные приложения": "Mobile Apps",
    "радиолюбительство": "Amateur Radio",
    "фото": "Photography",
    "дизайн и графика": "Design & Graphics",
    "веб-дизайн": "Web Design",
    "экономика": "Economics",
    "бизнес": "Business",
    "маркетинг": "Marketing",
    "медицина": "Medicine",
    "психология": "Psychology",
    "иностранные языки": "Foreign Languages",
    "русский язык": "Russian Language",
    "литература": "Literature",
    "поэзия": "Poetry",
    "детективы": "Detectives",
    "фантастика": "Science Fiction",
    "фэнтези": "Fantasy",
    "история": "History",
    "философия": "Philosophy",
    "наука": "Science",
    "техника": "Engineering",
    "электроника": "Electronics",
    "ремонт": "Repair",
    "строительство": "Construction",
    "авто": "Automotive",
    "путешествия": "Travel",
    "кулинария": "Cooking",
    "сад и огород": "Garden",
    "детям": "Children",
    "школьникам": "School",
    "студентам": "Students",
    "егэ": "Unified State Exam",
}


def _map_category(cat):
    """Best-effort static RU category -> EN, checking the full string, then
    its last '»' segment (subforum), then the first segment."""
    key = str(cat or "").strip().lower()
    if not key:
        return None
    if key in _RU_CAT_MAP:
        return _RU_CAT_MAP[key]
    segs = [x.strip() for x in re.split(r"[»|]", key) if x.strip()]
    for seg in (segs[-1:] + segs[:1]):
        if seg in _RU_CAT_MAP:
            return _RU_CAT_MAP[seg]
    return None


class _RuTranslator:
    """RU -> EN via MyMemory's free endpoint (no key), cached in memory.
    Translates titles and categories; falls back to Latin transliteration on
    any failure so results are always at least readable."""
    _URL = "https://api.mymemory.translated.net/get"

    def __init__(self):
        self._sem = asyncio.Semaphore(5)

    async def run(self, results):
        if not results:
            return results
        async with aiohttp.ClientSession(
            connector=get_connector(), connector_owner=False, trust_env=True
        ) as session:
            async def one(item):
                async with self._sem:
                    title = item.get("name") or ""
                    if title in _TRANS_CACHE:
                        item["name"] = _TRANS_CACHE[title]
                    elif _CYRILLIC_RE.search(title):
                        translated = await self._translate(session, title)
                        item["name"] = translated
                        _TRANS_CACHE[title] = translated
                    cat = item.get("category") or ""
                    if cat in _TRANS_CACHE:
                        item["category"] = _TRANS_CACHE[cat]
                    elif _CYRILLIC_RE.search(cat):
                        mapped = _map_category(cat)
                        if mapped:
                            item["category"] = mapped
                            _TRANS_CACHE[cat] = mapped
                        else:
                            translated = await self._translate(session, cat)
                            item["category"] = translated
                            _TRANS_CACHE[cat] = translated

            try:
                await asyncio.wait_for(
                    asyncio.gather(*(one(item) for item in results)),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                pass
        # Anything still Cyrillic (timed out / quota) -> transliterate now.
        for item in results:
            title = item.get("name") or ""
            if _CYRILLIC_RE.search(title):
                item["name"] = _transliterate(title)
            cat = item.get("category") or ""
            if _CYRILLIC_RE.search(cat):
                item["category"] = _transliterate(cat)
        return results

    async def _translate(self, session, title):
        try:
            url = "{0}?q={1}&langpair=ru|en".format(self._URL, quote(title[:480]))
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=6)
            ) as res:
                data = await res.json(content_type=None)
            out = ((data or {}).get("responseData") or {}).get("translatedText") or ""
            out = str(out).strip()
            if out and out.lower() != title.lower() and "QUERY LENGTH" not in out.upper():
                return out
        except Exception:
            pass
        return _transliterate(title)


_SESSION = "rutracker-tapi"
_SEARCH_TIMEOUT = aiohttp.ClientTimeout(total=60)
_ENRICH_TIMEOUT = aiohttp.ClientTimeout(total=45)

# RuTracker shows a hidden quick-login form (with login_username input) in the
# header DOM of every page, so that alone can never tell logged-in from guest.
# A real login page instead contains this full-page form heading; the
# captcha variant shows a different heading on the same form.
_LOGIN_PAGE_MARK = "Введите ваше имя и пароль"
_CAPTCHA_MARK = "код подтверждения"


def _cookie_list():
    cookies = []
    for part in _RUTRACKER_COOKIE.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            cookies.append({"name": name.strip(), "value": value.strip()})
    return cookies

# Warm Flaresolverr session, reused across flows so the Cloudflare challenge
# is only solved occasionally (each fresh solve takes ~10-15s). Rotated on a
# TTL and when a stale page is detected.
_sid = None
_sid_created = 0.0
_SESSION_TTL = 300.0
# Serialize Flaresolverr calls: concurrent flows sharing one warm session
# would interleave their fetches and return wrong pages/magnets.
_flare_lock = asyncio.Lock()


def _get_sid():
    global _sid, _sid_created
    now = time.time()
    if not _sid or now - _sid_created > _SESSION_TTL:
        old = _sid
        _sid = "rutracker-{}".format(uuid.uuid4().hex[:10])
        _sid_created = now
        # Old Flaresolverr session keeps its browser alive until deleted.
        close_flare_session_async(old, FLARESOLVERR_URL)
    return _sid


def _rotate_sid():
    global _sid, _sid_created
    old = _sid
    _sid = "rutracker-{}".format(uuid.uuid4().hex[:10])
    _sid_created = time.time()
    close_flare_session_async(old, FLARESOLVERR_URL)


def _rt_debug(*args):
    if (os.getenv("RUTRACKER_DEBUG") or "1").strip().lower() not in ("0", "false", "no"):
        print("[rutracker]", *args, flush=True)


# Cookies/UA captured from the last successful FlareSolverr solve (search
# already warms the session). dl.php is then fetched over plain HTTP with
# these - the browser has proven cf_clearance, so the CDN answers our
# datacenter IP directly instead of forcing a ~15s browser solve per file.
_plain_cookies = {}
_plain_ua = ""


def _cache_solution(solution):
    global _plain_cookies, _plain_ua
    cookies = {
        c.get("name"): c.get("value")
        for c in (solution.get("cookies") or [])
        if c.get("name") and c.get("value")
    }
    if cookies:
        _plain_cookies = cookies
    if solution.get("userAgent"):
        _plain_ua = solution.get("userAgent")


def _merge_cookie_list(cookies):
    """Layer the configured rutracker cookie (bb_session=...) over the
    Flaresolverr session cookies; the manual cookie keeps us logged in even
    when the session browser only solved Cloudflare."""
    merged = dict(cookies)
    for part in _cookie_list():
        k, _, v = part.partition("=")
        k = k.strip()
        if k and v:
            merged[k] = v
    return merged


def _dl_filename(headers):
    """Content-Disposition filename: RFC 5987 (filename*=UTF-8'') first,
    plain filename= second."""
    value = (headers or {}).get("content-disposition") or ""
    m = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", value, re.I)
    if m:
        try:
            return unquote(m.group(1).strip().strip('"'))
        except Exception:
            pass
    m = re.search(r'filename\s*=\s*"?([^";]+)', value, re.I)
    if m:
        return m.group(1).strip().strip('"')
    return ""


async def fetch_dl_torrent(url):
    """Fetch a rutracker dl.php .torrent behind Cloudflare.

    Fast path: the last FlareSolverr solve (search/enrich) already left
    cf_clearance + login cookies in ``_plain_cookies``, so dl.php is fetched
    over plain HTTP - no browser round-trip per download. Fallback:
    FlareSolverr request.get with the saved cookie (or the login-POST flow
    when no cookie is configured); its cookies are cached for the next
    download. Returns (torrent_bytes, upstream_filename) or None.
    """
    # Stage A - plain fetch with cookies from the last FlareSolverr solve
    if _plain_cookies:
        headers = {
            "User-Agent": _plain_ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Referer": url,
            "Accept": "*/*",
            "Accept-Language": "ru,en;q=0.9",
        }
        try:
            async with aiohttp.ClientSession(
                connector=get_connector(), connector_owner=False, trust_env=True
            ) as s:
                async with s.get(
                    url,
                    cookies=_merge_cookie_list(_plain_cookies),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True,
                ) as res:
                    body = await res.read()
                    ctype = str(res.headers.get("content-type") or "").lower()
                    up_name = _dl_filename(res.headers)
            _rt_debug(
                "dl.php plain", res.status, ctype,
                "bytes", len(body), "head", body[:20],
            )
            if body[:1] == b"d":
                return body, up_name
            _rt_debug("dl.php plain not a torrent -> flare fallback")
        except Exception as e:
            _rt_debug("dl.php plain failed:", repr(e))

    # Stage B - FlareSolverr browser fallback
    for attempt in (1, 2):
        cookies = _cookie_list()
        if cookies:
            payload = {
                "cmd": "request.get",
                "session": _get_sid(),
                "url": url,
                "maxTimeout": 30000,
                "cookies": cookies,
            }
        elif _RUTRACKER_USER and _RUTRACKER_PASS:
            parts = urlsplit(url)
            redirect = parts.path.lstrip("/")
            if parts.query:
                redirect += "?" + parts.query
            payload = {
                "cmd": "request.post",
                "url": "{}/forum/login.php".format(_RUTRACKER_BASE),
                "postData": urlencode(
                    {
                        "login_username": _RUTRACKER_USER,
                        "login_password": _RUTRACKER_PASS,
                        "login": "Вход",
                        "redirect": redirect,
                    }
                ),
                "maxTimeout": 30000,
                "session": _SESSION,
            }
        else:
            return None
        try:
            async with _flare_lock:
                async with aiohttp.ClientSession(
                    connector=get_connector(), connector_owner=False, trust_env=True
                ) as session:
                    async with session.post(
                        f"{FLARESOLVERR_URL}/v1",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=45),
                    ) as res:
                        data = await res.json(content_type=None)
            solution = data.get("solution") or {}
            status = solution.get("status")
            headers = solution.get("headers") or {}
            ctype = str(headers.get("content-type") or "").lower()
            _rt_debug(
                "dl.php flare attempt", attempt,
                "flare_status", data.get("status"),
                "msg", str(data.get("message") or "")[:100],
                "http", status, "ct", ctype,
            )
            if data.get("status") != "ok" or status != 200:
                _rt_debug("dl.php flare error -> rotate")
                _rotate_sid()
                continue
            _cache_solution(solution)
            raw = solution.get("response") or ""
            low = raw[:400].lower()
            if (
                "just a moment" in low
                or "cf-chl" in low
                or "<!doctype html" in low
            ):
                _rt_debug("dl.php challenge page -> rotate")
                _rotate_sid()
                continue
            body = raw.encode("utf-8", "replace")
            # FlareSolverr base64-encodes binary bodies; bencode dicts start
            # with 'd', so detect that and decode back to the real .torrent.
            try:
                dec = base64.b64decode(re.sub(r"\s+", "", raw), validate=True)
                if dec[:1] == b"d":
                    body = dec
            except Exception:
                pass
            if not body.startswith(b"d"):
                _rt_debug("dl.php not a torrent (head:", body[:50], ") -> rotate")
                _rotate_sid()
                continue
            return body, _dl_filename(headers)
        except Exception as e:
            _rt_debug("dl.php flare exception:", repr(e))
            _rotate_sid()
    return None

_RU_MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "июн": 6,
    "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}


class RuTracker:
    """RuTracker search via a self-hosted Flaresolverr instance.

    RuTracker is behind a Cloudflare JS challenge AND requires login for
    search. Flaresolverr solves the challenge with a headless browser. If
    ``RUTRACKER_COOKIE`` is set (from a manual browser login), it is sent
    with every request over a warm session — no login POST needed (logins
    are captcha-gated from datacenter IPs). Otherwise the login form's
    ``redirect`` field takes us straight to the search results page in one
    Flaresolverr request. Top results are enriched with magnet links from
    their topic pages.
    """

    _name = "RuTracker"

    def __init__(self):
        self.BASE_URL = "https://rutracker.org"
        self.LIMIT = None

    @staticmethod
    def _int(value):
        # RuTracker formats counts as "12 345" (space thousands separator)
        try:
            return int(re.sub(r"[^\d]", "", str(value)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_date(raw):
        raw = (raw or "").strip()
        m = re.search(r"(\d{1,2})-([А-Яа-я]{3})-(\d{2})", raw)
        if not m:
            return raw
        day, mon, yr = m.groups()
        num = _RU_MONTHS.get(mon.lower(), 0)
        if not num:
            return raw
        return "20{}-{:02d}-{:02d}".format(yr, num, int(day))

    @staticmethod
    def _is_login_page(html):
        return _LOGIN_PAGE_MARK in html or _CAPTCHA_MARK in html

    async def _flaresolverr(self, payload, timeout):
        async with _flare_lock:
            async with aiohttp.ClientSession(
                connector=get_connector(), connector_owner=False, trust_env=True
            ) as session:
                async with session.post(
                    f"{FLARESOLVERR_URL}/v1", json=payload, timeout=timeout
                ) as res:
                    data = await res.json(content_type=None)
        solution = data.get("solution") or {}
        if solution.get("status") != 200:
            return None
        html = solution.get("response") or ""
        if "Just a moment" in html or "cf-chl" in html:
            return None
        # Keep cookies/UA from every successful solve: the next dl.php
        # download then skips the browser round-trip (see fetch_dl_torrent).
        _cache_solution(solution)
        return html

    async def _fetch_html(self, url, timeout):
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 55000,
            "session": _get_sid(),
        }
        if _RUTRACKER_COOKIE:
            # Reuse a warm session across flows (challenge solves are slow,
            # ~10-15s each, and the API deadline is 28s). Explicit cookies
            # keep us logged in without any login POST.
            payload["cookies"] = _cookie_list()
        return await self._flaresolverr(payload, timeout)

    async def _login_and_fetch(self, redirect_target, timeout):
        """Log in and land directly on ``redirect_target`` in one request."""
        payload = {
            "cmd": "request.post",
            "url": "{}/forum/login.php".format(self.BASE_URL),
            "postData": urlencode(
                {
                    "login_username": _RUTRACKER_USER,
                    "login_password": _RUTRACKER_PASS,
                    "login": "Вход",
                    "redirect": redirect_target,
                }
            ),
            "maxTimeout": 55000,
            "session": _SESSION,
        }
        return await self._flaresolverr(payload, timeout)

    def _parse_rows(self, html):
        results = []
        soup = BeautifulSoup(html, "html.parser")
        # Raw RuTracker HTML has no <tbody> — rows sit directly in the table.
        for tr in soup.select("table.forumline tr"):
            name_el = tr.select_one(".row4 .wbr .med")
            if not name_el:
                continue
            name = name_el.get_text(" ", strip=True)
            link = name_el.get("href") or ""
            m = re.search(r"t=(\d+)", link)
            if not m or not name:
                continue
            tid = m.group(1)
            size_el = tr.select_one("a.small.tr-dl.dl-stub")
            size = ""
            if size_el:
                size = size_el.get_text(" ", strip=True)
                sm = re.search(r"(\d+(?:[.,]\d+)?\s*(?:B|KB|MB|GB|TB))", size, re.I)
                if sm:
                    size = sm.group(1)
            cat_el = tr.select_one(".row1 .f-name .gen")
            seeds_el = tr.select_one("b.seedmed")
            peers_el = tr.select_one("td.row4.leechmed.bold")
            date_el = tr.select_one("td.row4 p")
            dl_el = tr.select_one("td.row4.small.number-format")
            results.append(
                {
                    "tid": tid,
                    "name": name,
                    "size": size,
                    "date": self._format_date(date_el.get_text(" ", strip=True) if date_el else ""),
                    "seeders": self._int(seeds_el.get_text(strip=True) if seeds_el else ""),
                    "leechers": self._int(peers_el.get_text(strip=True) if peers_el else ""),
                    "downloads": self._int(dl_el.get_text(strip=True) if dl_el else ""),
                    "category": cat_el.get_text(" ", strip=True) if cat_el else "",
                    "url": "{}/forum/viewtopic.php?t={}".format(self.BASE_URL, tid),
                    "torrent": "{}/forum/dl.php?t={}".format(self.BASE_URL, tid),
                    "extension": "torrent",
                }
            )
        return results

    async def _magnet(self, tid, sem):
        async with sem:
            url = "{}/forum/viewtopic.php?t={}".format(self.BASE_URL, tid)
            try:
                html = await self._fetch_html(url, _ENRICH_TIMEOUT)
            except Exception:
                return None
            if html and self._is_login_page(html) and not _RUTRACKER_COOKIE:
                # Login did not carry over; log in and land on the topic
                # page in one request instead.
                try:
                    html = await self._login_and_fetch(
                        "viewtopic.php?t={}".format(tid), _ENRICH_TIMEOUT
                    )
                except Exception:
                    return None
            if not html or self._is_login_page(html):
                return None
            soup = BeautifulSoup(html, "html.parser")
            a = soup.select_one('a[href*="magnet:?xt=urn:btih:"]')
            if not a:
                return None
            href = a.get("href") or ""
            m = re.search(r"btih:([a-fA-F0-9]{40})", href)
            if not m:
                return None
            return {"hash": m.group(1).upper(), "magnet": href}

    async def search(self, query, page, limit):
        start_time = time.time()
        self.LIMIT = limit or None
        try:
            page = max(int(page or 1) - 1, 0)
        except (TypeError, ValueError):
            page = 0
        start = page * 50
        url = "{}/forum/tracker.php?nm={}".format(self.BASE_URL, quote_plus(query))
        if start:
            url += "&start={}".format(start)
        if _RUTRACKER_COOKIE:
            try:
                html = await self._fetch_html(url, _SEARCH_TIMEOUT)
            except Exception:
                return None
        else:
            if not _RUTRACKER_USER or not _RUTRACKER_PASS:
                return None
            redirect = "tracker.php?nm={}".format(quote_plus(query))
            if start:
                redirect += "&start={}".format(start)
            try:
                html = await self._login_and_fetch(redirect, _SEARCH_TIMEOUT)
            except Exception:
                return None
        if not html or self._is_login_page(html):
            # Login page/captcha came back → auth failed (bad creds/blocked).
            return None
        raw = self._parse_rows(html)
        if not raw and not self._is_login_page(html):
            counter = re.search(r"Результатов поиска:\s*(\d+)", html)
            if counter and int(counter.group(1)) > 0:
                # Warm session served a stale/empty page — rotate and retry
                # once before giving up.
                _rotate_sid()
                try:
                    html = await self._fetch_html(url, _SEARCH_TIMEOUT)
                except Exception:
                    return None
                if not html or self._is_login_page(html):
                    return None
                raw = self._parse_rows(html)
        if self.LIMIT:
            raw = raw[: self.LIMIT]
        extras = []
        if raw and FLARESOLVERR_ENRICH:
            # Same-session fetches must stay sequential to avoid races, and a
            # hard cap keeps the whole flow under the API's 28s deadline
            # (timeout → results without magnets instead of a 504).
            sem = asyncio.Semaphore(1)
            enrich_n = min(len(raw), ENRICH_CAP)
            try:
                extras = await asyncio.wait_for(
                    asyncio.gather(
                        *(self._magnet(row["tid"], sem) for row in raw[:enrich_n]),
                        return_exceptions=True,
                    ),
                    timeout=12.0,
                )
            except asyncio.TimeoutError:
                extras = []
        results = []
        for idx, row in enumerate(raw):
            extra = (
                extras[idx]
                if idx < len(extras) and isinstance(extras[idx], dict)
                else None
            )
            info_hash = (extra or {}).get("hash")
            results.append(
                {
                    "name": row["name"],
                    "size": row["size"],
                    "date": row["date"],
                    "seeders": row["seeders"],
                    "leechers": row["leechers"],
                    "downloads": row["downloads"],
                    "uploader": "",
                    "category": row["category"],
                    "url": row["url"],
                    # dl.php is Cloudflare-fronted; the torrent_file proxy
                    # fetches it through FlareSolverr so leech links work.
                    "torrent": row["torrent"],
                    "extension": "torrent",
                    "hash": info_hash,
                    "magnet": (extra or {}).get("magnet"),
                }
            )
        if results:
            results = await _RuTranslator().run(results)
        return {
            "data": results,
            "current_page": page + 1,
            "total_pages": 1,
            "time": time.time() - start_time,
            "total": len(results),
        }
