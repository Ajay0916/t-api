import re

_SPLIT_RE = re.compile(
    r"\s*(?:uploaded|uploded|digitized|scanned|added|assembled|contributed|posted)\s*by\b",
    re.I,
)
_PREFIX_RE = re.compile(
    r"^(?:written|narrated|authored|compiled|edited|translated|read)\s*"
    r"(?:by)?\s*[:/-]*\s*",
    re.I,
)
_JUNK_RE = re.compile(
    r"dept|department|university|college|library|archive\.org|digital|"
    r"youtube|channel|admin|volunteer|website|link|download",
    re.I,
)


def clean_archive_creators(creator):
    """Extract a clean author list from an archive.org creator field.

    The field is user-supplied and often contains junk like
    "Written By:- X Uploded By:- Y" or channel names; only values that
    look like an author name survive so the WZML Author tag stays clean.
    """
    if isinstance(creator, list):
        values = [str(c) for c in creator]
    elif isinstance(creator, str):
        values = [creator]
    else:
        return None
    out = []
    for v in values:
        # Multi-author strings use "; " separators; keep the primary author.
        v = re.split(r"\s*;\s*", v)[0]
        v = _SPLIT_RE.split(v)[0]
        v = _PREFIX_RE.sub("", v)
        v = re.sub(r"\([^)]*\)", "", v)
        v = v.strip(" -:;.,")
        if not v or len(v) < 2 or v in out:
            continue
        if _JUNK_RE.search(v):
            continue
        out.append(v)
    return out or None
