"""Read a bounded, attributed snapshot from publisher-operated feeds."""

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary
from xml.etree import ElementTree

import httpx

from atoms.core.config import settings

NEWS_FILE = "src/data/editorial-feed.json"
_CHINA = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class Feed:
    url: str
    publisher: str
    section: str
    host: str
    timezone: tzinfo = UTC


_FEEDS = (
    Feed("https://www.stats.gov.cn/sj/zxfb/rss.xml", "国家统计局", "数据发布", "www.stats.gov.cn", _CHINA),
    Feed("https://www.stats.gov.cn/sj/sjjd/rss.xml", "国家统计局", "数据解读", "www.stats.gov.cn", _CHINA),
    Feed("https://www.federalreserve.gov/feeds/press_monetary.xml", "美联储", "货币政策", "www.federalreserve.gov"),
)

_cache: dict | None = None
_expires: datetime | None = None
_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()


def wants_editorial_feed(request: str) -> bool:
    return bool(
        re.search(r"(?:财经|金融|经济|商业)(?:新闻|资讯)|\b(?:financial|finance|economic) news\b", request, re.I)
    )


def has_editorial_snapshot(source: str | None) -> bool:
    if not source:
        return False
    try:
        snapshot = json.loads(source)
    except ValueError:
        return False
    return isinstance(snapshot, dict) and snapshot.get("status") in ("available", "stale", "unavailable")


def parse_article(element: ElementTree.Element, feed: Feed, now: datetime) -> dict | None:
    title = " ".join((element.findtext("title") or "").split())
    link = (element.findtext("link") or "").strip()
    url = urlsplit(link)
    if not title or url.scheme != "https" or url.netloc != feed.host:
        return None
    date_text = element.findtext("pubDate") or ""
    try:
        try:
            published = datetime.fromisoformat(date_text)
        except ValueError:
            published = parsedate_to_datetime(date_text)
    except (ValueError, TypeError, OverflowError):
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=feed.timezone)
    if not now - timedelta(days=45) <= published <= now + timedelta(minutes=10):
        return None
    return {
        "id": hashlib.sha256(link.encode()).hexdigest()[:16],
        "title": title[:240],
        "url": link,
        "published_at": published.astimezone(UTC).isoformat(),
        "source": feed.publisher,
        "section": feed.section,
    }


async def _read_feed(client: httpx.AsyncClient, feed: Feed, now: datetime) -> list[dict] | None:
    parser = ElementTree.XMLPullParser(events=("end",))
    items = []
    size = 0
    tail = b""
    try:
        async with client.stream("GET", feed.url) as response:
            response.raise_for_status()
            async for part in response.aiter_bytes(chunk_size=8192):
                size += len(part)
                if size > 768 * 1024:
                    return items
                if b"<!DOCTYPE" in tail + part or b"<!ENTITY" in tail + part:
                    raise ValueError("Unsupported publisher response")
                tail = part[-10:]
                parser.feed(part)
                for _, element in parser.read_events():
                    if element.tag == "item":
                        if article := parse_article(element, feed, now):
                            items.append(article)
                        element.clear()
                if len(items) >= 8:
                    return items[:8]
            parser.close()
    except (httpx.HTTPError, ElementTree.ParseError, ValueError):
        return None
    return items


async def editorial_snapshot() -> dict:
    global _cache, _expires
    now = datetime.now(UTC)
    config = settings()
    unavailable = {"status": "unavailable", "collected_at": None, "items": []}
    if config.app_env == "test" and config.test_fixture:
        return unavailable
    if _cache and _expires and now < _expires:
        return _cache
    lock = _locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())
    async with lock:
        now = datetime.now(UTC)
        if _cache and _expires and now < _expires:
            return _cache
        try:
            async with (
                asyncio.timeout(8),
                httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client,
            ):
                results = await asyncio.gather(*(_read_feed(client, feed, now) for feed in _FEEDS))
        except TimeoutError:
            results = []
        unique = {item["url"]: item for result in results if result for item in result}
        finished = datetime.now(UTC)
        if unique:
            items = sorted(unique.values(), key=lambda item: item["published_at"], reverse=True)
            _cache = {"status": "available", "collected_at": finished.isoformat(), "items": items}
            _expires = finished + timedelta(minutes=15)
        else:
            recent = (_cache or {}).get("items", [])
            recent = [
                item for item in recent if datetime.fromisoformat(item["published_at"]) >= finished - timedelta(days=45)
            ]
            _cache = {**_cache, "status": "stale", "items": recent} if recent else unavailable
            _expires = finished + timedelta(minutes=1)
        return _cache
