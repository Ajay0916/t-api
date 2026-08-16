import asyncio
import os
import re

# r.jina.ai serves 403 to full Chrome UAs from some networks; a plain UA
# gets the page. Optional JINA_API_KEY raises the reader rate limit.
_JINA_UA = "Mozilla/5.0"
_JINA_KEY = os.environ.get("JINA_API_KEY", "")
_JINA_DELAY = float(os.environ.get("LEADS_JINA_DELAY", "1.2"))
_WB_TIMEOUT = float(os.environ.get("LEADS_WB_TIMEOUT", "8"))

_last_jina = 0.0
_jina_lock = asyncio.Lock()

_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


async def _curl(args, timeout, family=None):
    try:
        cmd = ["curl", "-sL", "--compressed", "-A", _JINA_UA, "-w", "\n%{http_code}",
               "--max-time", str(timeout)]
        if family:
            cmd.insert(2, family)
        proc = await asyncio.create_subprocess_exec(
            *cmd, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
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


async def jina_fetch(url, timeout=45):
    """Fetch a page through the r.jina.ai reader (raw HTML). Paced so a
    free reader account is not hammered; JINA_API_KEY lifts the cap."""
    global _last_jina
    async with _jina_lock:
        wait = _JINA_DELAY - (asyncio.get_event_loop().time() - _last_jina)
        if wait > 0:
            await asyncio.sleep(wait)
        args = ["-H", "X-Return-Format: html"]
        if _JINA_KEY:
            args += ["-H", "Authorization: Bearer " + _JINA_KEY]
        body = await _curl(args + ["https://r.jina.ai/" + url], timeout)
        _last_jina = asyncio.get_event_loop().time()
        return body


async def wayback_fetch(url, years=("2024", "2023", "2022", "2021")):
    """Latest Wayback snapshot body for a URL, raw HTML (id_ mode)."""
    for year in years:
        body = await _curl(
            ["https://web.archive.org/web/{}id_/{}{}".format(year, "https://", url.lstrip("https://"))],
            _WB_TIMEOUT,
        )
        if body:
            return body
        await asyncio.sleep(0.3)
    return None


# Standard GSTIN shape: 2-digit state, 10-char PAN (5 letters + 4 digits +
# 1 letter), entity code, mandatory 'Z', checksum char.
GSTIN_RE = re.compile(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
GST_MASK_RE = re.compile(r"[0-9]{2}\*{8,}[0-9A-Z]{3}")

# Boundary-safe mobile match: a 10-digit run inside a longer digit string
# (internal ids, fb-pixel numbers, product ids) is NOT a phone number.
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[- ]?)?([6-9][0-9]{9})(?!\d)")


def gstin_valid(g):
    """True when the 15th char is the GSTN check digit of the first 14
    (base-36 weighted sum, mod-36 Luhn-style). Rejects fake/placeholder
    GSTINs that happen to match the shape."""
    if not g or not GSTIN_RE.fullmatch(g):
        return False
    total = 0
    for i in range(14):
        v = _B36.index(g[i])
        p = v * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return _B36[(36 - total % 36) % 36] == g[14]


PNS_RE = re.compile(r"pnsNumber[\"']?\s*[:=]\s*[\"']\+?91?-?([0-9]{6,12})")
LANDLINE_RE = re.compile(r"(?<!\d)0[0-9]{2,4}[- ]?[0-9]{6,8}(?!\d)")


def extract_phones(text):
    """Deduplicated Indian numbers found in a page: pnsNumber (the number
    IndiaMART's call button reveals) first, then boundary-safe mobiles, then
    landlines. Only well-formed 10-digit runs are kept - internal ids and
    fb-pixel noise are excluded by the phone regex boundaries."""
    seen, out = set(), []
    for m in PNS_RE.finditer(text or ""):
        n = m.group(1)
        if n not in seen:
            seen.add(n)
            out.append(n)
    for m in PHONE_RE.finditer(text or ""):
        n = m.group(1)
        if n not in seen:
            seen.add(n)
            out.append(n)
    for m in LANDLINE_RE.finditer(text or ""):
        n = m.group(0).replace(" ", "").replace("-", "")
        if len(n) >= 10 and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def mask_matches(masked, full):
    """Live masked GST (07**********1Z9) vs archived full GSTIN check."""
    if not masked or not full:
        return False
    return full.startswith(masked[:2]) and full.endswith(masked[-3:])
