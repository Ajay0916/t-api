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
- **Mirror rotation** — 1337x, YTS, Bitsearch, AudiobookBay, LimeTorrents (5 hosts), KickAss auto-failover to next mirror when one is blocked.
- **Live tracker magnets** — magnets built with fresh working trackers, not dead hardcoded ones.
- **Search pagination** — parsers fetch multiple pages till the limit is reached.
- **Combo search + health tracking** — `/all/search`, `/all/trending`, `/all/recent` run all sites with per-site deadline; blocked/down sites auto-skip; 1337x pushed to the end of combo results.
- **Concurrency caps** — bounded detail-page scraping so the VPS IP doesn't get blocked.
- **Query encoding fixes** — multi-word queries (`bob proctor`) work on every site.
- **Cleaner output** — seeders/leechers/downloads normalized to int.
- **Caching** — repeated queries served from cache (`fresh=1` to bypass).
- **API key auth** — optional `PYTORRENTS_API_KEY` via `x-api-key` header.

---

## 🌐 Sites

**Torrents:** `1337x`, `tgx`, `torlock`, `piratebay`, `nyaasi`, `zooqle`, `kickass`, `bitsearch`, `magnetdl`, `libgen`, `yts`, `limetorrent`, `torrentfunk`, `glodls`, `torrentproject`, `ybt`, `ext`, `torrentdownload`, `magnetz`

**Audiobooks:** `audiobookbay`

**Courses:** `freecourseweb`

**Books / Indian content:** `hindibooks`, `hindiaudio`, `archivebooks`, `annasarchive`, `pdfdrive`

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

---

## 📡 API Endpoints

| Endpoint | Params |
| :------- | :----- |
| `GET /api/v1/sites` | — |
| `GET /api/v1/sites/config` | — |
| `GET /api/v1/search` | `site` ✅, `query` ✅, `limit`, `page`, `fresh` |
| `GET /api/v1/trending` | `site` ✅, `limit`, `category`, `page` |
| `GET /api/v1/recent` | `site` ✅, `limit`, `category`, `page` |
| `GET /api/v1/category` | `site` ✅, `query` ✅, `category` ✅, `limit`, `page` |
| `GET /api/v1/all/search` | `query` ✅, `limit` (per-site results combined) |
| `GET /api/v1/all/trending` | `limit` |
| `GET /api/v1/all/recent` | `limit` |

**Example**

```sh
curl "http://localhost:8009/api/v1/search?site=1337x&query=eternals&limit=10"
curl "http://localhost:8009/api/v1/all/search?query=kgf&limit=5"
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

Set `PYTORRENTS_API_KEY` env var, then send requests with header `x-api-key: <your-key>`.

---

## ☁️ Deploy

<a href="https://render.com/deploy?repo=https://github.com/Ajay0916/t-api">
<img src="https://render.com/images/deploy-to-render-button.svg" alt="Deploy to Render" />
</a>

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy)

---

## License

Original: [MIT](https://github.com/Ryuk-me/Torrent-Api-py/blob/main/LICENSE) © [Ryuk-me](https://github.com/Ryuk-me)
