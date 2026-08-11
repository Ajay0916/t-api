import asyncio
import re
import time
from urllib.parse import quote as requests_quote
import aiohttp
from helper.session import get_connector
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import X1337
from constants.headers import HEADER_AIO, AIO_TIMEOUT

HOSTS = [
    X1337,
    "https://1337x.to",
    "https://1337x.st",
    "https://x1337x.ws",
    "https://1337xx.to",
]


STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "with", "to",
    "at", "by", "vs", "feat", "ft", "hd", "web", "x264", "x265", "h264",
}


def _tidy(tok):
    return re.sub(r"(?<=[a-z])0+(\d)", r"\1", tok)


def _tok_match(q, t):
    if q == t:
        return True
    q2, t2 = _tidy(q), _tidy(t)
    if q2 == t2:
        return True
    shorter = q if len(q) <= len(t) else t
    if len(shorter) >= 3 and (t.startswith(q) or q.startswith(t)):
        return True
    if re.search(r"\d", shorter) and (t2.startswith(q2) or q2.startswith(t2)):
        return True
    return False


def _query_relevant(name, query, threshold=0.6):
    qtoks = [
        t
        for t in re.sub(r"[^a-z0-9]+", " ", (query or "").lower()).split()
        if t not in STOPWORDS and not (len(t) < 2 and t.isalpha())
    ]
    if not qtoks:
        return True
    norm_name = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).split()
    if not norm_name:
        return False
    joined = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    hits = 0
    for q in qtoks:
        if any(_tok_match(q, t) for t in norm_name) or q in joined:
            hits += 1
    return hits / len(qtoks) >= threshold


class x1337:
    _name = "1337x"
    def __init__(self):
        self.BASE_URL = X1337
        self.LIMIT = None

    async def _fetch_page(self, session, path):
        for host in HOSTS:
            url = host + path
            htmls = await Scraper().get_all_results(session, url)
            if htmls and htmls[0]:
                self.BASE_URL = host
                return htmls
        return None

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                async with session.get(url, headers=HEADER_AIO, timeout=AIO_TIMEOUT) as res:
                    html = await res.text(encoding="ISO-8859-1")
                    soup = BeautifulSoup(html, "html.parser")
                    try:
                        magnet = soup.select_one(
                            ".no-top-radius > div > ul > li > a"
                        )["href"]
                        obj["magnet"] = magnet
                        obj["hash"] = re.search(
                            r"([{a-f\d,A-F\d}]{32,40})\b", magnet
                        ).group(0)
                        try:
                            uls = soup.find_all("ul", class_="list")[1]
                            lis = uls.find_all("li")[0]
                            imgs = [
                                img["data-original"]
                                for img in (soup.find("div", id="description")).find_all("img")
                                if img["data-original"].endswith((".png", ".jpg", ".jpeg"))
                            ]
                            files = [
                                f.text for f in soup.find("div", id="files").find_all("li")
                            ]
                            if len(imgs) > 0:
                                obj["screenshot"] = imgs
                            obj["category"] = lis.find("span").text
                            obj["files"] = files
                            poster = soup.select_one("div.torrent-image img")["src"]
                            if str(poster).startswith("//"):
                                obj["poster"] = "https:" + poster
                            elif str(poster).startswith("/"):
                                obj["poster"] = self.BASE_URL + poster
                        except (IndexError, AttributeError, TypeError):
                            ...
                    except (IndexError, AttributeError, TypeError):
                        ...
            except:
                return None

    async def _get_torrent(self, result, session, urls):
        tasks = []
        sem = asyncio.Semaphore(10)
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(session, url, result["data"][idx], sem)
                    )
                    tasks.append(task)
        await asyncio.gather(*tasks)
        return result

    def _parser(self, htmls):
        try:
            for html in htmls:
                soup = BeautifulSoup(html, "html.parser")
                list_of_urls = []
                my_dict = {"data": []}
                trs = soup.select("tbody tr")
                for tr in trs:
                    td = tr.find_all("td")
                    name = td[0].find_all("a")[-1].text
                    if name and _query_relevant(name, getattr(self, "_query", None)):
                        href = td[0].find_all("a")[-1]["href"]
                        if href.startswith("http"):
                            url = self.BASE_URL + "/" + href.split("/", 3)[-1]
                        else:
                            url = self.BASE_URL + href
                        list_of_urls.append(url)
                        seeders = td[1].text
                        leechers = td[2].text
                        date = td[3].text
                        size = td[4].text.replace(seeders, "")
                        uploader = td[5].find("a").text

                        my_dict["data"].append(
                            {
                                "name": name,
                                "size": size,
                                "date": date,
                                "seeders": seeders,
                                "leechers": leechers,
                                "url": url,
                                "uploader": uploader,
                            }
                        )
                    if len(my_dict["data"]) == self.LIMIT:
                        break
                try:
                    pages = soup.select(".pagination li a")
                    my_dict["current_page"] = int(pages[0].text)
                    tpages = pages[-1].text
                    if tpages == ">>":
                        my_dict["total_pages"] = int(pages[-2].text)
                    else:
                        my_dict["total_pages"] = int(pages[-1].text)
                except:
                    ...
                return my_dict, list_of_urls
        except:
            return None, None

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            self.LIMIT = limit
            start_time = time.time()
            path = "/search/{}/{}/".format(requests_quote(query), page)
            result = await self.parser_result(start_time, path, session, page=page, query=query)
            if result is not None and len(result["data"]) > 0:
                return result
            # 1337x search only surfaces matches for the first word of
            # multi-word queries, so fall back to searching the distinctive
            # tokens (e.g. "bob proctor" -> search "proctor") and keep only
            # results relevant to the full query. Try the most distinctive
            # token first to minimize extra requests.
            tokens = [
                t
                for t in re.sub(r"[^a-z0-9]+", " ", (query or "").lower()).split()
                if t not in STOPWORDS and not (len(t) < 2 and t.isalpha())
            ]
            if len(tokens) < 2:
                return result
            tokens.sort(key=len, reverse=True)
            for tok in tokens:
                path = "/search/{}/{}/".format(requests_quote(tok), page)
                res = await self.parser_result(start_time, path, session, page=page, query=query)
                if res is not None and len(res["data"]) > 0:
                    return res
            return result

    async def parser_result(self, start_time, path, session, page, query=None):
        self._query = query
        htmls = await self._fetch_page(session, path)
        if htmls is None:
            return None
        result, urls = self._parser(htmls)
        if result is not None:
            results = await self._get_torrent(result, session, urls)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            if query is None:
                return results
            while True:
                if len(results["data"]) >= self.LIMIT:
                    results["data"] = results["data"][0 : self.LIMIT]
                    results["total"] = len(results["data"])
                    return results
                if page >= 25:
                    break
                page = page + 1
                path = "/search/{}/{}/".format(requests_quote(query), page)
                htmls = await self._fetch_page(session, path)
                if htmls is None:
                    break
                result, urls = self._parser(htmls)
                if result is not None:
                    if len(result["data"]) > 0:
                        res = await self._get_torrent(result, session, urls)
                        for obj in res["data"]:
                            results["data"].append(obj)
                        try:
                            results["current_page"] = res["current_page"]
                        except:
                            ...
                        results["time"] = time.time() - start_time
                        results["total"] = len(results["data"])
                    else:
                        break
                else:
                    break
            return results
        return result

    async def trending(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            if not category:
                path = "/home/"
            else:
                path = "/popular-{}".format(category.lower())
            return await self.parser_result(start_time, path, session, page)

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            if not category:
                path = "/trending"
            else:
                path = "/cat/{}/{}/".format(
                    str(category).capitalize(), page
                )
            return await self.parser_result(start_time, path, session, page)

    async def search_by_category(self, query, category, page, limit):
        async with aiohttp.ClientSession(connector=get_connector(), connector_owner=False) as session:
            start_time = time.time()
            self.LIMIT = limit
            path = "/category-search/{}/{}/{}/".format(
                requests_quote(query), category.capitalize(), page
            )
            return await self.parser_result(start_time, path, session, page, query)
