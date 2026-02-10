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
    """
    Fetch weather using Open-Meteo (No API Key).
    """
    cached = _load_cache(WEATHER_CACHE)
    if cached:
        # Check if city matches? For now assume straightforward Usage
        return cached

    if not city: city = "Delhi" 
    
    try:
        # 1. Geocode to get Lat/Lon
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=en&format=json"
        geo_resp = requests.get(geo_url, timeout=REQUEST_TIMEOUT)
        if not geo_resp.ok: return None
        
        results = geo_resp.json().get("results")
        if not results: return None
        
        lat = results[0]["latitude"]
        lon = results[0]["longitude"]
        place_name = results[0]["name"]
        
        # 2. Get Weather
        w_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        w_resp = requests.get(w_url, timeout=REQUEST_TIMEOUT)
        if not w_resp.ok: return None
        
        data = w_resp.json()
        current = data.get("current_weather", {})
        
        # Map WMO codes to text (simple version)
        # https://open-meteo.com/en/docs
        wmo_code = current.get("weathercode", 0)
        condition_text = "Clear sky"
        if wmo_code in [1, 2, 3]: condition_text = "Partly cloudy"
        elif wmo_code in [45, 48]: condition_text = "Foggy"
        elif wmo_code in [51, 53, 55, 61, 63, 65]: condition_text = "Rain"
        elif wmo_code in [71, 73, 75]: condition_text = "Snow"
        elif wmo_code >= 95: condition_text = "Thunderstorm"
        
        result = {
            "current": {
                "temp_c": current.get("temperature"),
                "condition": {"text": condition_text},
                "city": place_name
            },
            "_ts": time.time()
        }
        
        WEATHER_CACHE.write_text(json.dumps(result))
        return result

    except Exception as e:
        print(f"[weather] Error: {e}")
        return None


def fetch_news():
    """Fetch Top Headlines from Google News RSS (No API Key)"""
    try:
        # Google News RSS (India Edition)
        url = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
        resp = requests.get(url, timeout=5)
        
        if resp.status_code == 200:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.content)
            items = root.findall('.//item')
            headlines = []
            
            for item in items[:5]: # Top 5 headlines
                title = item.find('title').text
                # Remove source suffix (e.g. " - Times of India")
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0]
                headlines.append(title)
            
            if headlines:
                return "Here are the top headlines:\n" + "\n".join(f"- {h}" for h in headlines)
                
    except Exception as e:
        print(f"[news] Error fetching news: {e}")
        
    return "Sorry, I couldn't get the latest news right now."
