"""Discover genre references from Steam's public storefront before planning."""

import asyncio
from datetime import UTC, datetime
from html import unescape
import json
import re
from time import monotonic

import httpx

from .config import settings

RESEARCH_FILE = "src/agent/research.json"
STORE = "https://store.steampowered.com"
_TAG = {
    "fps": 1663, "racing": 699, "platformer": 1625, "falling_blocks": 1664,
    "puzzle": 1664, "strategy": 9, "survival": 1662, "fighting": 1743,
    "role_playing": 122, "sports": 701, "simulation": 599, "roguelike":1716,
    "rhythm":1752, "card":1666, "sandbox":3810, "other": 19,
    "arcade_platformer": 1625, "match3": 1665, "tower_defense": 1645,
}
_GENRE_ID = {"racing": "9", "sports": "18", "strategy": "2", "role_playing": "3"}
_cache: dict[str, tuple[float, dict]] = {}


async def _json(client: httpx.AsyncClient, path: str, params: dict):
    async with client.stream("GET", STORE + path, params=params) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > 384_000:
                raise ValueError("Storefront response exceeds limit")
    return json.loads(body)


async def _game(client: httpx.AsyncClient, app_id: str, genre: str):
    try:
        entry = await _json(client, "/api/appdetails", {"appids": app_id, "l": "english", "cc": "us"})
        data = entry[app_id]["data"]
        if data.get("type") != "game" or data.get("coming_soon") or (data.get("release_date") or {}).get("coming_soon"):
            return None
        genres = [item["id"] for item in data.get("genres", [])]
        if genre in _GENRE_ID and _GENRE_ID[genre] not in genres:
            return None
        description = unescape(re.sub(r"<[^>]*>", " ", data.get("short_description", "")))
        if genre == "racing" and not re.search(r"\brac(?:e|es|er|ers|ing)\b|motorsport|\bsimrac",description,re.I):
            return None
        return {"title": " ".join(data["name"].split())[:140], "url": f"{STORE}/app/{app_id}/",
                "description": " ".join(description.split()[:24])[:300]}
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError):
        return None


async def find_game_references(genre: str) -> dict:
    genre = genre if genre in _TAG else "other"
    if settings().test_fixture:
        return {"status": "fixture", "genre": genre, "games": []}
    cached = _cache.get(genre)
    if cached and cached[0] > monotonic():
        return cached[1]

    games = []
    try:
        async with asyncio.timeout(9), httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False) as client:
            query = {"tags": _TAG[genre], "category1": 998, "filter": "topsellers", "count": 16,
                     "infinite": 1, "l": "english", "cc": "us"}
            page = await _json(client, "/search/results/", query)
            ids = list(dict.fromkeys(re.findall(r'data-ds-itemkey="App_([0-9]{1,10})"', page["results_html"])))
            details = await asyncio.gather(*(_game(client, app_id, genre) for app_id in ids[:12]))
            games = [game for game in details if game][:4]
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError, TimeoutError):
        pass
    result = {"status": "live" if games else "fallback", "genre": genre, "games": games,
              "source": f"{STORE}/search/?tags={_TAG[genre]}&filter=topsellers",
              "checked_at": datetime.now(UTC).isoformat()}
    _cache[genre] = (monotonic() + (600 if games else 45), result)
    return result
