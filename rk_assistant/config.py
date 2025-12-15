"""
Lightweight configuration for the RK Pi client.

Optimized for Raspberry Pi Zero W (512MB RAM). Keep third‑party
dependencies minimal and avoid loading large models unless needed.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Load .env file if it exists (strictly use .env, no hardcoded secrets)
_env_file = BASE_DIR.parent / ".env"
if _env_file.exists():
    try:
        with open(_env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Only set if not already in environment (env vars take precedence)
                    if key not in os.environ:
                        os.environ[key] = value
    except Exception:
        pass  # Silently fail if .env can't be read
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# File paths
SLUG_FILE = BASE_DIR / "slug.txt"  # Pre-seeded unique 9-digit slug
WEATHER_CACHE = DATA_DIR / "weather.json"
NEWS_CACHE = DATA_DIR / "news.json"
WIFI_CREDENTIALS = DATA_DIR / "wifi_credentials.json"
LAST_AUDIO = DATA_DIR / "last_command.wav"
PROBE_AUDIO = DATA_DIR / "probe.wav"

# Audio capture
SAMPLE_RATE = 16000
CHANNELS = 1
MAX_RECORD_SECONDS = 15  # safety cap to avoid memory use
WAKE_WORD = "rk"

# Backend
BACKEND_URL = "https://rk-ai-backend.onrender.com/voice"
BACKEND_BASE_URL = "https://rk-ai-backend.onrender.com"  # Base URL for text endpoint
REQUEST_TIMEOUT = 30  # seconds (increased for slow backend responses)

# Error logging
ERROR_LOG_FILE = BASE_DIR / "backend_error_log.txt"

# Weather/News (set via env)
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
WEATHER_API_BASE = "https://api.weatherapi.com/v1"
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
WEATHER_CITY_DEFAULT = os.getenv("WEATHER_CITY_DEFAULT", "Delhi")
NEWS_COUNTRY_DEFAULT = os.getenv("NEWS_COUNTRY_DEFAULT", "in")

# Bluetooth RFCOMM channel
BT_CHANNEL = int(os.getenv("BT_CHANNEL", "3"))

# Bluetooth Speaker MAC (for auto-connect)
BLUETOOTH_SPEAKER_MAC = os.getenv("BLUETOOTH_SPEAKER_MAC", "E0:C8:22:85:F8:32")

# Preferred BlueZ adapter (e.g., hci1)
BLUETOOTH_HCI = os.getenv("BLUETOOTH_HCI", "hci1")

# Offline command whitelist (50 max). Keep short strings for cheap checks.
OFFLINE_COMMANDS = [
    "play music", "pause music", "resume music", "stop music",
    "volume up", "volume down", "mute", "unmute",
    "next song", "previous song",
    "what's the weather", "weather", "news", "headlines",
    "time", "date",
    "announce", "announcement",
    "battery", "status",
    "restart", "reboot", "shutdown",
    "wifi status", "internet status", "ip address",
    "record", "start recording", "stop recording",
    "set timer", "set alarm", "cancel alarm",
    "brightness up", "brightness down",
    "open bluetooth", "close bluetooth",
    "connect wifi", "wifi connect",
    "ping", "speed test",
    "who are you", "help", "commands",
    "sleep", "wake", "quiet", "louder",
    "save note", "read note",
    "led on", "led off"
][:50]

# PocketSphinx model path (optional; uses system default if not set)
POCKETSPHINX_MODEL_DIR = os.getenv("POCKETSPHINX_MODEL_DIR", str(DATA_DIR / "pocketsphinx-model"))

# Appwrite (optional; required for auto-slug repair)
APPWRITE_ENDPOINT = os.getenv("APPWRITE_ENDPOINT", "")
APPWRITE_PROJECT_ID = os.getenv("APPWRITE_PROJECT_ID", "")
APPWRITE_API_KEY = os.getenv("APPWRITE_API_KEY", "")
APPWRITE_DB_ID = os.getenv("APPWRITE_DB_ID", "")
APPWRITE_USERS_COLLECTION = os.getenv("APPWRITE_USERS_COLLECTION", "")

