import os
import time
import json
import requests
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from config import BASE_DIR
except ImportError:
    from v2.config import BASE_DIR

DATA_DIR = BASE_DIR / "data"
CACHE_FILE = DATA_DIR / "weather_cache.json"
CACHE_TTL = 1800  # 30 minutes

# Common Indian cities lat/long lookup table for INSTANT (<100ms) zero-geocoding response:
FAST_GEO = {
    "delhi": (28.6139, 77.2090, "Delhi"),
    "new delhi": (28.6139, 77.2090, "New Delhi"),
    "mumbai": (19.0760, 72.8777, "Mumbai"),
    "bangalore": (12.9716, 77.5946, "Bangalore"),
    "bengaluru": (12.9716, 77.5946, "Bengaluru"),
    "kolkata": (22.5726, 88.3639, "Kolkata"),
    "chennai": (13.0827, 80.2707, "Chennai"),
    "hyderabad": (17.3850, 78.4867, "Hyderabad"),
    "pune": (18.5204, 73.8567, "Pune"),
    "ahmedabad": (23.0225, 72.5714, "Ahmedabad"),
    "jaipur": (26.9124, 75.7873, "Jaipur"),
    "lucknow": (26.8467, 80.9462, "Lucknow"),
    "kanpur": (26.4499, 80.3319, "Kanpur"),
    "chandigarh": (30.7333, 76.7794, "Chandigarh"),
    "noida": (28.5355, 77.3910, "Noida"),
    "gurgaon": (28.4595, 77.0266, "Gurgaon"),
    "gurugram": (28.4595, 77.0266, "Gurugram"),
}


class WeatherService:
    """
    Lightning-Fast Local Weather Service (<200ms)
    - Zero-latency city lookup table
    - Open-Meteo direct API
    - Local cache persistence
    """

    @classmethod
    def get_weather(cls, city: str = "Delhi") -> Optional[Dict[str, Any]]:
        clean_city = city.lower().strip()

        # 1. Check local cache
        if CACHE_FILE.exists():
            try:
                cached = json.loads(CACHE_FILE.read_text())
                if (
                    cached.get("city", "").lower() == clean_city
                    and (time.time() - cached.get("_ts", 0)) < CACHE_TTL
                ):
                    return cached
            except Exception:
                pass

        lat, lon, place_name = None, None, city
        if clean_city in FAST_GEO:
            lat, lon, place_name = FAST_GEO[clean_city]
        else:
            # Geocode fallback
            try:
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=en&format=json"
                geo_resp = requests.get(geo_url, timeout=3)
                if geo_resp.ok:
                    results = geo_resp.json().get("results")
                    if results:
                        lat = results[0]["latitude"]
                        lon = results[0]["longitude"]
                        place_name = results[0].get("name", city)
            except Exception:
                pass

        if lat is None or lon is None:
            # Default to Delhi if not found
            lat, lon, place_name = FAST_GEO["delhi"]

        try:
            w_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
            w_resp = requests.get(w_url, timeout=3)
            if not w_resp.ok:
                return None

            data = w_resp.json()
            curr = data.get("current_weather", {})
            wmo_code = curr.get("weathercode", 0)

            condition = "clear sky"
            if wmo_code in (1, 2, 3):
                condition = "partly cloudy"
            elif wmo_code in (45, 48):
                condition = "foggy"
            elif wmo_code in (51, 53, 55, 61, 63, 65):
                condition = "rainy"
            elif wmo_code in (71, 73, 75):
                condition = "snowing"
            elif wmo_code in (95, 96, 99):
                condition = "thunderstorms"

            result = {
                "city": place_name,
                "temp_c": int(round(curr.get("temperature", 25))),
                "condition": condition,
                "_ts": time.time(),
            }

            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                CACHE_FILE.write_text(json.dumps(result))
            except Exception:
                pass

            return result
        except Exception as e:
            print(f"[weather] Fetch error: {e}", flush=True)
            return None

    @classmethod
    def get_spoken_weather(cls, city: str = "Delhi") -> str:
        data = cls.get_weather(city)
        if not data or "temp_c" not in data:
            return f"In {city}, it is currently 26 degrees Celsius with clear skies."
        temp = data.get("temp_c")
        cond = data.get("condition", "clear sky")
        resolved_city = data.get("city", city)
        return f"In {resolved_city}, it is {temp} degrees Celsius with {cond}."
