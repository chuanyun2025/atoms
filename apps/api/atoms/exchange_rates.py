"""Fetch a dated, public ECB snapshot for exchange-rate projects."""
import asyncio
from datetime import date
import re
import time
from weakref import WeakKeyDictionary
from xml.etree import ElementTree

import httpx

from .config import settings

SOURCE = "欧洲中央银行"
SOURCE_URL = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"
XML_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
RATES_FILE = "src/data/exchange-rates.json"
_NAMESPACE = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"
_cache: dict | None = None
_expires = 0.0
_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()


def wants_exchange_rates(prompt: str, base: dict | None) -> bool:
    return bool(re.search(r"汇率|外汇|\bexchange rates?\b|\bforex\b", prompt, re.I)
                or (base and RATES_FILE in base.get("files", {})))


def parse_exchange_rates(xml: bytes) -> dict:
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise ValueError("ECB XML 声明不受支持")
    root = ElementTree.fromstring(xml)
    snapshot = root.find(f".//{_NAMESPACE}Cube[@time]")
    if snapshot is None:
        raise ValueError("ECB 数据缺少观察日期")
    observed_on = date.fromisoformat(snapshot.attrib["time"]).isoformat()
    rates = []
    for currency in snapshot.findall(f"{_NAMESPACE}Cube"):
        code = currency.get("currency", "")
        rate = currency.get("rate", "")
        if re.fullmatch(r"[A-Z]{3}", code) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", rate):
            if float(rate) > 0:
                rates.append({"currency": code, "rate": rate})
    if not rates:
        raise ValueError("ECB 数据缺少参考汇率")
    return {"status":"available","source":SOURCE,"source_url":SOURCE_URL,
            "base":"EUR","observed_on":observed_on,"rates":rates}


async def reference_rates() -> dict:
    global _cache, _expires
    unavailable = {"status":"unavailable","source":SOURCE,"source_url":SOURCE_URL,
                   "base":"EUR","observed_on":None,"rates":[]}
    config = settings()
    if config.app_env == "test" and config.test_fixture:
        return unavailable
    now = time.monotonic()
    if _cache and now < _expires:
        return _cache
    lock = _locks.setdefault(asyncio.get_running_loop(), asyncio.Lock())
    async with lock:
        now = time.monotonic()
        if _cache and now < _expires:
            return _cache
        try:
            async with httpx.AsyncClient(timeout=5,follow_redirects=False,trust_env=False) as client:
                async with client.stream("GET",XML_URL) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > 64*1024:
                            raise ValueError("ECB 数据超过大小上限")
            _cache = parse_exchange_rates(bytes(body))
            _expires = time.monotonic() + 15*60
        except (httpx.HTTPError, ElementTree.ParseError, ValueError):
            _cache = {**_cache,"status":"stale"} if _cache and _cache["rates"] else unavailable
            _expires = time.monotonic() + 60
        return _cache
