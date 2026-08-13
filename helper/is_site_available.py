from torrents.hindibooks import HindiBooks
from torrents.hindiaudio import HindiAudio
from torrents.archivebooks import ArchiveBooks
from torrents.audiobookbay import AudiobookBay
from torrents.bitsearch import Bitsearch
from torrents.extratorrent import ExtraTorrent
from torrents.magnetz import Magnetz
from torrents.torrentdownload import TorrentDownloads
from torrents.tdp import TDP
from torrents.kickass import Kickass
from torrents.libgen import Libgen
from torrents.limetorrents import Limetorrent
from torrents.magnet_dl import Magnetdl
from torrents.nyaa_si import NyaaSi
from torrents.pirate_bay import PirateBay
from torrents.torlock import Torlock
from torrents.torrent_galaxy import TorrentGalaxy
from torrents.torrentfunk import TorrentFunk
from torrents.torrentProject import TorrentProject
from torrents.x1337 import x1337
from torrents.your_bittorrent import YourBittorrent
from torrents.yts import Yts
from torrents.pimpmymind import PimpMyMind
from torrents.rutracker import RuTracker

all_sites = {
    "1337x": {
        "website": x1337,
        "trending_available": True,
        "trending_category": True,
        "search_by_category": True,
        "recent_available": True,
        "recent_category_available": True,
        "categories": [
            "anime",
            "music",
            "games",
            "tv",
            "apps",
            "documentaries",
            "other",
            "xxx",
            "movies",
        ],
        "limit": 100,
    },
    "tgx": {
        "website": TorrentGalaxy,
        "trending_available": True,
        "trending_category": True,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": True,
        "categories": [
            "anime",
            "music",
            "games",
            "tv",
            "apps",
            "documentaries",
            "other",
            "xxx",
            "movies",
            "books",
        ],
        "limit": 50,
    },
    "magnetdl": {
        "website": Magnetdl,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": True,
        # e-books
        "categories": ["apps", "movies", "music", "games", "tv", "books"],
        "limit": 40,
    },
    "tdp": {
        "website": TDP,
        "trending_available": True,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": False,
        "categories": [],
        "limit": 45,
    },
    "torrentdownload": {
        "website": TorrentDownloads,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": False,
        "recent_category_available": False,
        "categories": [],
        "limit": 50,
    },
    "magnetz": {
        "website": Magnetz,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": False,
        "categories": [],
        "limit": 50,
    },
    "bitsearch": {
        "website": Bitsearch,
        "trending_available": True,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": False,
        "recent_category_available": False,
        "categories": [],
        "limit": 50,
    },
    "kickass": {
        "website": Kickass,
        "trending_available": True,
        "trending_category": True,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": True,
        "categories": [
            "anime",
            "music",
            "games",
            "tv",
            "apps",
            "documentaries",
            "other",
            "xxx",
            "movies",
            "books",
        ],  # television applications
        "limit": 50,
    },
    "limetorrent": {
        "website": Limetorrent,
        "trending_available": True,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": True,
        "categories": [
            "anime",
            "music",
            "games",
            "tv",
            "apps",
            "other",
            "movies",
            "books",
        ],  # applications and tv-shows
        "limit": 50,
    },
    "pimpmymind": {
        "website": PimpMyMind,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": False,
        "categories": [],
        "limit": 30,
    },


    "torrentfunk": {
        "website": TorrentFunk,
        "trending_available": True,
        "trending_category": True,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": True,
        "categories": [
            "anime",
            "music",
            "games",
            "tv",
            "apps",
            "xxx",
            "movies",
            "books",
        ],  # television # software #adult # ebooks
        "limit": 50,
    },
    "ext": {
        "website": ExtraTorrent,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": False,
        "recent_category_available": False,
        "categories": [],
        "limit": 50,
    },
    "torlock": {
        "website": Torlock,
        "trending_available": True,
        "trending_category": True,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": True,
        "categories": [
            "anime",
            "music",
            "games",
            "tv",
            "apps",
            "documentaries",
            "other",
            "xxx",
            "movies",
            "books",
            "images",
        ],  # ebooks
        "limit": 50,
    },
    "torrentproject": {
        "website": TorrentProject,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": False,
        "recent_category_available": False,
        "categories": [],
        "limit": 20,
    },
    "ybt": {
        "website": YourBittorrent,
        "trending_available": True,
        "trending_category": True,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": True,
        "categories": [
            "anime",
            "music",
            "games",
            "tv",
            "apps",
            "xxx",
            "movies",
            "books",
            "pictures",
            "other",
        ],  # book -> ebooks
        "limit": 20,
    },
    "piratebay": {
        "website": PirateBay,
        "trending_available": True,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": True,
        "categories": ["tv"],
        "limit": 50,
    },
    "nyaasi": {
        "combo_available": False,
        "website": NyaaSi,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": False,
        "categories": [],
        "limit": 50,
    },
    "yts": {
        "website": Yts,
        "trending_available": True,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": False,
        "categories": [],
        "limit": 20,
    },

    "hindibooks": {
        "website": HindiBooks,
        "combo_available": False,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": False,
        "recent_category_available": False,
        "categories": [],
        "limit": 20,
    },
    "hindiaudio": {
        "website": HindiAudio,
        "combo_available": False,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": False,
        "recent_category_available": False,
        "categories": [],
        "limit": 15,
    },
    "archivebooks": {
        "website": ArchiveBooks,
        "combo_available": False,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": False,
        "recent_category_available": False,
        "categories": [],
        "limit": 20,
    },
    "audiobookbay": {
        "website": AudiobookBay,
        "combo_available": False,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": True,
        "recent_category_available": False,
        "categories": [],
        "limit": 20,
    },
    "libgen": {
        "combo_available": False,
        "website": Libgen,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": False,
        "recent_category_available": False,
        "categories": [],
        "limit": 25,
    },
    "rutracker": {
        "combo_available": False,
        "website": RuTracker,
        "trending_available": False,
        "trending_category": False,
        "search_by_category": False,
        "recent_available": False,
        "recent_category_available": False,
        "categories": [],
        "limit": 50,
    },
}

sites_config = {
    key: {
        **site_info, 
        "website": site_info["website"]._name
    } for key, site_info in all_sites.items()
}

def check_if_site_available(site):
    if site in all_sites.keys():
        return all_sites
    return False
