"""
Weather Service for RK AI Assistant V2.
Uses Open-Meteo REST API (free, reliable, NO API key required).
Includes 10-minute cache to conserve Pi network bandwidth and CPU.
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
import requests

from config import BASE_DIR

CACHE_FILE = BASE_DIR / "data" / "weather_cache.json"
CACHE_TTL = 600  # 10 minutes cache


class WeatherService:
    @staticmethod
    def get_weather(city: str = "Delhi") -> Optional[Dict[str, Any]]:
        """
        Fetches current weather for the specified city.
        Returns parsed weather info dict or None if unavailable.
        """
        city = (city or "Delhi").strip()

        # 1. Check cache
        if CACHE_FILE.exists():
            try:
                cached = json.loads(CACHE_FILE.read_text())
                if (
                    cached.get("city", "").lower() == city.lower()
                    and (time.time() - cached.get("_ts", 0)) < CACHE_TTL
                ):
                    return cached
            except Exception:
                pass

        try:
            # 2. Geocode city name to lat/long
            geo_url = (
                f"https://geocoding-api.open-meteo.com/v1/search"
                f"?name={city}&count=1&language=en&format=json"
            )
            geo_resp = requests.get(geo_url, timeout=5)
            if not geo_resp.ok:
                return None

            results = geo_resp.json().get("results")
            if not results:
                return None

            lat = results[0]["latitude"]
            lon = results[0]["longitude"]
            place_name = results[0].get("name", city)

            # 3. Forecast / current weather
            w_url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat}&longitude={lon}&current_weather=true"
            )
            w_resp = requests.get(w_url, timeout=5)
            if not w_resp.ok:
                return None

            data = w_resp.json()
            curr = data.get("current_weather", {})

            # Map WMO weather code to English description
            wmo_code = curr.get("weathercode", 0)
            condition = "Clear sky"
            if wmo_code in (1, 2, 3):
                condition = "Partly cloudy"
            elif wmo_code in (45, 48):
                condition = "Foggy"
            elif wmo_code in (51, 53, 55, 61, 63, 65):
                condition = "Rainy"
            elif wmo_code in (71, 73, 75):
                condition = "Snowing"
            elif wmo_code >= 95:
                condition = "Thunderstorm"

            result = {
                "city": place_name,
                "temp_c": curr.get("temperature"),
                "windspeed": curr.get("windspeed"),
                "condition": condition,
                "_ts": time.time(),
            }

            # Cache to disk
            try:
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                CACHE_FILE.write_text(json.dumps(result))
            except Exception:
                pass

            return result

        except Exception as e:
            print(f"[weather] Error fetching weather for {city}: {e}")
            return None

    @classmethod
    def get_spoken_weather(cls, city: str = "Delhi") -> str:
        """Returns concise text suitable for TTS."""
        data = cls.get_weather(city)
        if not data or "temp_c" not in data:
            return f"Sorry, I couldn't get the current weather for {city} right now."

        temp = data.get("temp_c")
        cond = data.get("condition", "clear")
        resolved_city = data.get("city", city)
        return f"In {resolved_city}, it's currently {temp} degrees Celsius with {cond.lower()}."
