"""Weather and news fetchers with simple caching."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional

import requests

from .config import (
    NEWS_API_KEY,
    NEWS_CACHE,
    NEWS_COUNTRY_DEFAULT,
    REQUEST_TIMEOUT,
    WEATHER_API_BASE,
    WEATHER_API_KEY,
    WEATHER_CACHE,
    WEATHER_CITY_DEFAULT,
)

CACHE_TTL = 600  # 10 minutes


def _load_cache(path: Path) -> Optional[Dict]:
    if path.exists():
        try:
            obj = json.loads(path.read_text())
            if time.time() - obj.get("_ts", 0) < CACHE_TTL:
                return obj
        except Exception:
            return None
    return None


def fetch_weather(city: str = WEATHER_CITY_DEFAULT) -> Optional[Dict]:
    cached = _load_cache(WEATHER_CACHE)
    if cached:
        return cached
    if not WEATHER_API_KEY:
        return None
    url = f"{WEATHER_API_BASE}/current.json?key={WEATHER_API_KEY}&q={city}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.ok:
            data = resp.json()
            data["_ts"] = time.time()
            WEATHER_CACHE.write_text(json.dumps(data))
            return data
    except Exception:
        return None
    return None


def fetch_news(country: str = NEWS_COUNTRY_DEFAULT) -> Optional[Dict]:
    cached = _load_cache(NEWS_CACHE)
    if cached:
        return cached
    if not NEWS_API_KEY:
        return None
    url = f"https://newsapi.org/v2/top-headlines?country={country}&pageSize=5&apiKey={NEWS_API_KEY}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.ok:
            data = resp.json()
            data["_ts"] = time.time()
            NEWS_CACHE.write_text(json.dumps(data))
            return data
    except Exception:
        return None
    return None


