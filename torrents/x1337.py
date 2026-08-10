import asyncio
import re
import time
from urllib.parse import quote as requests_quote
import aiohttp
from bs4 import BeautifulSoup
from helper.asyncioPoliciesFix import decorator_asyncio_fix
from helper.html_scraper import Scraper
from constants.base_url import X1337
from constants.headers import HEADER_AIO


class x1337:
    _name = "1337x"
    def __init__(self):
        self.BASE_URL = X1337
        self.LIMIT = None

    def _tokens(self, query):
        return [token for token in query.lower().split() if len(token) > 2]

    def _matches(self, name, tokens):
        if not tokens:
            return True
        name = name.lower()
        return all(token in name for token in tokens)

    @decorator_asyncio_fix
    async def _individual_scrap(self, session, url, obj, sem):
        async with sem:
            try:
                async with session.get(url, headers=HEADER_AIO) as res:
                    html = await res.text(encoding="ISO-8859-1")
                    soup = BeautifulSoup(html, "html.parser")
                    try:
                        magnet = soup.select_one(".no-top-radius > div > ul > li > a")[
                            "href"
                        ]
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
        sem = asyncio.Semaphore(5)
        tasks = []
        for idx, url in enumerate(urls):
            for obj in result["data"]:
                if obj["url"] == url:
                    task = asyncio.create_task(
                        self._individual_scrap(
                            session, url, result["data"][idx], sem
                        )
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
                    if name:
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

    async def _collect(self, result, urls, session, tokens):
        if tokens:
            kept_data = []
            kept_urls = []
            for obj, url in zip(result["data"], urls):
                if self._matches(obj["name"], tokens):
                    kept_data.append(obj)
                    kept_urls.append(url)
            result["data"] = kept_data
            urls = kept_urls
        if self.LIMIT and len(result["data"]) > self.LIMIT:
            result["data"] = result["data"][0 : self.LIMIT]
            urls = urls[0 : self.LIMIT]
        return await self._get_torrent(result, session, urls)

    async def search(self, query, page, limit):
        async with aiohttp.ClientSession() as session:
            self.LIMIT = limit
            start_time = time.time()
            url = self.BASE_URL + "/search/{}/{}/".format(requests_quote(query), page)
            results = await self.parser_result(
                start_time, url, session, page=page, query=query
            )
            if results is not None and len(results["data"]) == 0:
                tokens = self._tokens(query)
                if len(tokens) > 1:
                    self.LIMIT = min(limit, 20)
                    url = self.BASE_URL + "/search/{}/{}/".format(
                        requests_quote(tokens[-1]), page
                    )
                    fallback = await self.parser_result(
                        start_time, url, session, page=page, query=tokens[-1]
                    )
                    if fallback is not None and len(fallback["data"]) > 0:
                        fallback["data"].sort(
                            key=lambda obj: not self._matches(obj["name"], tokens)
                        )
                        results = fallback
            return results

    async def parser_result(self, start_time, url, session, page, query=None):
        tokens = self._tokens(query) if query is not None else None
        htmls = await Scraper().get_all_results(session, url)
        result, urls = self._parser(htmls)
        if result is not None:
            results = await self._collect(result, urls, session, tokens)
            results["time"] = time.time() - start_time
            results["total"] = len(results["data"])
            if query is None:
                if self.LIMIT:
                    results["data"] = results["data"][0 : self.LIMIT]
                    results["total"] = len(results["data"])
                return results
            while True:
                if len(results["data"]) >= self.LIMIT:
                    results["data"] = results["data"][0 : self.LIMIT]
                    results["total"] = len(results["data"])
                    return results
                page = page + 1
                if page > 3:
                    break
                url = self.BASE_URL + "/search/{}/{}/".format(
                    requests_quote(query), page
                )
                htmls = await Scraper().get_all_results(session, url)
                result, urls = self._parser(htmls)
                if result is None:
                    break
                if len(result["data"]) == 0:
                    break
                res = await self._collect(result, urls, session, tokens)
                for obj in res["data"]:
                    results["data"].append(obj)
                try:
                    results["current_page"] = res["current_page"]
                except:
                    ...
                results["time"] = time.time() - start_time
                results["total"] = len(results["data"])
            return results
        return result

    async def trending(self, category, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            if not category:
                url = self.BASE_URL + "/home/"
            else:
                url = self.BASE_URL + "/popular-{}".format(category.lower())
            return await self.parser_result(start_time, url, session, page)

    async def recent(self, category, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            if not category:
                url = self.BASE_URL + "/trending"
            else:
                url = self.BASE_URL + "/cat/{}/{}/".format(
                    str(category).capitalize(), page
                )
            return await self.parser_result(start_time, url, session, page)

    async def search_by_category(self, query, category, page, limit):
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            self.LIMIT = limit
            url = self.BASE_URL + "/category-search/{}/{}/{}/".format(
                requests_quote(query), category.capitalize(), page
            )
            return await self.parser_result(start_time, url, session, page, query)
