<h2 align='center'>Torrents Api ✨</h2>
<p align="center">
<a href="https://github.com/Ajay0916/t-api"><img src="https://img.shields.io/badge/Repo-t--api-red.svg?style=for-the-badge&logo=github"></a>
<a href="https://github.com/Ajay0916/t-api/stargazers/"><img src="https://img.shields.io/github/stars/Ajay0916/t-api?color=brown&style=flat-square"></a>
<a href="https://github.com/Ajay0916/t-api/network/members"><img src="https://img.shields.io/github/forks/Ajay0916/t-api?color=lightgrey&style=flat-square"></a>
</p>

<p align="center">
<b>26 sites</b> — Torrents, Indian &amp; International Courses, Indian Books/Audiobooks, eBooks, Anime &amp; Audiobooks in one API.
<br>Built &amp; maintained by <b>Ajay</b> on top of <a href="https://github.com/Ryuk-me/Torrent-Api-py">Torrent-Api-py</a>.
</p>

---

## 🙏 Credits

- [Ryuk-me](https://github.com/Ryuk-me) — original [Torrent-Api-py](https://github.com/Ryuk-me/Torrent-Api-py). All base scrapers &amp; API design belong to him. Go star his repo ❤️
- [ngosang/trackerslist](https://github.com/ngosang/trackerslist) — live trackers used to build magnet links.
- [WZML-X](https://github.com/SilentDemonSD/WZML-X) — search results are used in its API mode.

---

## ✨ What's Unique Here

- **26 sites** — general torrents + courses + Indian books/audiobooks + eBooks + anime + audiobooks.
- **Mirror rotation** — 1337x, YTS, Bitsearch, AudiobookBay, LimeTorrents (5 hosts), KickAss & ExtraTorrent auto-failover to next mirror when one is blocked.
- **Full proxy support** — every scraper honors `HTTP_PROXY`/`HTTPS_PROXY` (`trust_env`), so you can route all site traffic through a proxy/Tor when your IP gets blocked (same as upstream Torrent-Api-py).
- **Live tracker magnets** — magnets built with fresh working trackers, not dead hardcoded ones.
- **`.torrent` for every hash** — results with an infohash automatically get a working `.torrent` download link (itorrents.net), so WZML-X buttons never stay empty (TGX, TDP, MagnetDL, KickAss, Magnetz, FreeCourseWeb, TorrentProject, PirateBay).
- **Cloudflare-safe TGX** — TorrentGalaxy JSON API fetched over a proper SSL connector with host fallback (`.info` / `.one`) + retries, so it survives Cloudflare resets.
- **Recent feeds** — new arrivals for Magnetz (native RSS), FreeCourseWeb, PimpMyMind & AudioBookBay (RSS), so `/all/recent` covers courses + audiobooks too.
- **Faster detail scraping** — ExtraTorrent, MagnetDL & TorLock concurrency tuned; ExtraTorrent went from ~24s to ~5s for 10 results, TorLock from ~12s to ~4s.
- **Combo merges every site** — `limit` caps how many results each site fetches, but the merged output returns everything collected (deduped by infohash, sorted by seeders).
- **Result filters & sort** — `min_seeders`, `category`, `sort=seeders|size|date`, `order=asc|desc`, movie filters `quality=480|720|1080|4k` & `language=hindi|english|tamil|...`, book filter `format=pdf|epub|mobi|azw3|...`, size range `min_size`/`max_size` (`500MB`, `2GB`, or bare MB numbers) on both `/all/search` and `/search`.
- **Auto-detected metadata** — every result is enriched with `quality` (`480p/720p/1080p/4K`) and `language` (`Hindi, English, Tamil...`) for movies, and `format` (`PDF/EPUB/MOBI...`) for books, detected from the release name / extension / download URL — WZML and API clients can show them without parsing titles. Multi-quality releases (`720p 480p`) match either quality filter.
- **Smart filter fallback** — if a strict filter combo finds nothing (e.g. Hindi + 1080p when the Hindi release is only 4K), the API relaxes quality → format → category and returns the best available results (marked `relaxed_filters: true`). The `language` filter is **never** relaxed: a Hindi search never silently returns English releases. Language-specific searches also retry only the sites that were slow/empty in the first pass before relaxing anything.
- **Safe language detection** — language tags use word-start matching (`[Hin-Eng]`, `HinDub`, `[Tam+Tel]` all work) without false positives from substrings (`ben` in "Unbent", `mar` in "Driftmark", `tel` in "Hotel").
- **Torrent file proxy** — `/api/v1/torrent_file?url=...` fetches a `.torrent` through this server so WZML Direct Links survive CDN blocks.
- **Manual site toggle** — `POST /api/v1/status/{site}/disable` (or `/enable`) blocks/unblocks a site instantly, no restart. Disabled sites also vanish from `/api/v1/sites`, so WZML hides their buttons too (WZML re-fetches the site list every time it renders the site menu). `/api/v1/sites` returns both `supported_sites` and `sites[{site,name}]`, and `/api/v1/sites/status` shows every site's `enabled`/`manual_blocked` state.
- **Combo de-duplicates by infohash** — same torrent from multiple sites takes only the best-seeder row (before the limit cap), so WZML result slots never fill with repeats.
- **Infohash link fallback** — every result carrying an infohash automatically gets both a magnet AND a `.torrent` Direct Link (itorrents.net), so WZML always has a working button even when a scraper only exposes the hash.
- **Site status endpoint** — `/api/v1/status` shows every site's health: blocked state, cooldown remaining, fail count, last error, combo availability & per-site limit.
- **GZip responses** — API responses are gzip-compressed automatically (big combo payloads reach WZML faster).
- **API key auth** — optional `PYTORRENT_API_KEY` via `x-api-key` header. ⚠️ WZML-X doesn't send headers, so **don't enable the key if WZML-X uses this API** (keep it unset for public/WZML use).
- **Cache survives restarts** — search/combo/RSS caches persist to `cache_data/` and reload on boot, so the first query after a VPS deploy isn't slow again.
- **1337x `.torrent` links** — infohash-based .torrent links now also added for 1337x results.
- **Search pagination** — parsers fetch multiple pages till the limit is reached.
- **Combo search + health tracking** — `/all/search`, `/all/trending`, `/all/recent` run all sites under one hard 18s cap (true deadline, results never drag); slow-but-alive sites are retried next round instead of being blacklisted; hard-failed/down sites auto-skip; 1337x pushed to the end of combo results.
- **Concurrency caps** — bounded detail-page scraping so the VPS IP doesn't get blocked.
- **Query encoding fixes** — multi-word queries (`bob proctor`) work on every site.
- **Cleaner output** — seeders/leechers/downloads normalized to int.
- **No empty WZML buttons** — results with neither a magnet nor a `.torrent`/direct link are dropped from every response, so every rendered row has a working download button.
- **Lenient params** — `site`/`query` are trimmed, so trailing spaces (WZML sends `query=kgf `) no longer break or skew results.
- **Author metadata on books** — every book result carries `authors` (libgen, annasarchive, hindiaudio, archivebooks, audiobookbay), cleaned of `Uploded By`/role junk, so WZML shows a proper Author tag.
- **Hindi book downloads fixed** — the torrent proxy serves non-ASCII titles via RFC 5987 `filename*` (Hindi/Tamil names no longer 500), auto-appends the right extension, and hindibooks prefers live file hosts (archive.org → Zoho → Google Drive → `book.php` → legacy `quick-download`).
- **AudiobookBay resilience** — mirror rotation with real-page validation (parked/sale pages skipped), plus one quick retry on transient Cloudflare blocks; blocked sites now return a clear *"try again"* message instead of *"change your IP"*.
- **Caching** — repeated queries served from cache (`fresh=1` to bypass).
- --

## 🌐 Sites

**Torrents:** `1337x`, `tgx`, `torlock`, `piratebay`, `nyaasi`, `pimpmymind`, `kickass`, `bitsearch`, `magnetdl`, `libgen`, `yts`, `limetorrent`, `torrentfunk`, `tdp`, `torrentproject`, `ybt`, `ext`, `torrentdownload`, `magnetz`

**Audiobooks:** `audiobookbay`

**Courses:** `freecourseweb`, `rutracker` (RuTracker — Cloudflare-protected and login-gated, so it needs a self-hosted [Flaresolverr](https://github.com/flaresolverr/Flaresolverr) instance (`FLARESOLVERR_URL`, default `http://127.0.0.1:8191`) plus a free RuTracker account (`RUTRACKER_USERNAME` / `RUTRACKER_PASSWORD`). Logins are captcha-gated from datacenter IPs, so the recommended way is to log in once in a browser and pass the session cookie via `RUTRACKER_COOKIE='bb_session=...; bb_guid=...'` — the bot then skips the login POST and uses the cookie on every request (fallback: one-shot login via the form's `redirect` field). Top results are enriched with magnet links)

**Books / Indian content:** `hindibooks`, `hindiaudio`, `archivebooks`, `annasarchive`

> Per-site `limit` and available methods: [`helper/is_site_available.py`](helper/is_site_available.py)

---

## 🚀 Installation

```sh
git clone https://github.com/Ajay0916/t-api
cd t-api
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py                  # → http://localhost:8009
```

VPS par 24×7 chalane ke liye:

```sh
nohup ./venv/bin/python main.py > server.log 2>&1 &
```

IP block hote par proxy/Tor se chalane ke liye (sab sites support karti hain):

```sh
export HTTP_PROXY="http://proxy-host:port"
nohup ./venv/bin/python main.py > server.log 2>&1 &
```

Docker se chalane ke liye (cache persistent, auto-restart):

```sh
docker compose up -d --build
```

---

## 📡 API Endpoints

| Endpoint | Params |
| :------- | :----- |
| `GET /api/v1/sites` | — returns `supported_sites` plus `sites[{site,name}]` |
| `GET /api/v1/sites/config` | — |
| `GET /api/v1/sites/status` | — every site's `enabled`/`manual_blocked`/`blocked`, cooldown, fail count, combo/trending/recent availability |
| `GET /api/v1/search` | `site` ✅, `query` ✅, `limit`, `page`, `fresh`, `min_seeders`, `category`, `sort`, `order`, `quality`, `language`, `format`, `min_size`, `max_size` |
| `GET /api/v1/trending` | `site` ✅, `limit`, `category`, `page` |
| `GET /api/v1/recent` | `site` ✅, `limit`, `category`, `page` |
| `GET /api/v1/category` | `site` ✅, `query` ✅, `category` ✅, `limit`, `page` |
| `GET /api/v1/all/search` | `query` ✅, `limit`, `min_seeders`, `category`, `sort`, `order`, `fresh`, `quality`, `language`, `format`, `min_size`, `max_size` |
| `GET /api/v1/torrent_file` | `url` ✅, `name` — proxies a .torrent file through this server |
| `POST /api/v1/status/{site}/disable` · `/enable` | manually block/unblock a site without restart (disabled sites disappear from `/api/v1/sites` → WZML buttons) |
| `GET /api/v1/all/trending` | `limit` |
| `GET /api/v1/all/recent` | `limit` |

**Example**

```sh
curl "http://localhost:8009/api/v1/search?site=1337x&query=eternals&limit=10"
curl "http://localhost:8009/api/v1/all/search?query=kgf&limit=5"
# Hindi 1080p/4K movies only
curl "http://localhost:8009/api/v1/all/search?query=kgf&limit=5&language=hindi&quality=1080"
# Books in epub only
curl "http://localhost:8009/api/v1/search?site=libgen&query=python&limit=5&format=epub"
# Small files only (under 1GB) without piratebay in the combo
curl "http://localhost:8009/api/v1/all/search?query=kgf&limit=5&max_size=1GB"
```

**Response**

```json
{
  "data": [
    {
      "name": "Eternals.2021.1080p.WEBRip.1600MB.DD5.1.x264-GalaxyRG",
      "size": "1.6 GB",
      "seeders": 3674,
      "leechers": 983,
      "url": "https://www.1377x.to/torrent/5110228/...",
      "category": "Movies",
      "magnet": "magnet:?xt=urn:btih:20F8D7C2...",
      "hash": "20F8D7C2942B143E6E2A0FB5562CDE7EE1B17822"
    }
  ],
  "current_page": 1,
  "total_pages": 7,
  "time": 1.27,
  "total": 10
}
```

---

## 🔐 Authentication

Set `PYTORRENT_API_KEY` env var, then send requests with header `x-api-key: <your-key>`.

> ⚠️ **WZML-X warning:** WZML-X calls the API directly without headers. If you use this API with WZML-X, keep the key unset or WZML search will fail with 403.

---

## ☁️ Deploy

<a href="https://render.com/deploy?repo=https://github.com/Ajay0916/t-api">
<img src="https://render.com/images/deploy-to-render-button.svg" alt="Deploy to Render" />
</a>

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy)

---

## License

Original: [MIT](https://github.com/Ryuk-me/Torrent-Api-py/blob/main/LICENSE) © [Ryuk-me](https://github.com/Ryuk-me)
