"""
Lightweight configuration for the RK Pi client.

Optimized for Raspberry Pi Zero W (512MB RAM). Keep third‑party
dependencies minimal and avoid loading large models unless needed.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Load .env file if it exists (strictly use .env, no hardcoded secrets)
# Check BASE_DIR first (package dir), then parent (project root)
_search_paths = [BASE_DIR / ".env", BASE_DIR.parent / ".env"]
for _env_file in _search_paths:
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
            # Stop after finding the first valid .env? Or load both? 
            # Usually one is enough, but loading both doesn't hurt (first one found takes precedence if we break, 
            # but we continue here so last one might overwrite unless we check existence).
            # Actually, the logic `if key not in os.environ` protects us. 
            # So the first file loaded wins for any given key.
            # We should probably break after finding one, or just load all.
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

# Microphone configuration for live STT
MIC_DEVICE_INDEX = int(os.getenv("MIC_DEVICE_INDEX", "-1"))  # -1 for default
MIC_SAMPLE_RATE = int(os.getenv("MIC_SAMPLE_RATE", str(SAMPLE_RATE)))
GTTS_ENABLE = os.getenv("GTTS_ENABLE", "1") == "1"
GTTS_PLAYBACK_TIMEOUT = int(os.getenv("GTTS_PLAYBACK_TIMEOUT", "120"))
GTTS_LANG = os.getenv("GTTS_LANG", "en")
GTTS_TLD = os.getenv("GTTS_TLD", "co.in")
MPG123_OUTPUT = os.getenv("MPG123_OUTPUT", "pulse")

# Backend
BACKEND_URL = "https://rk-ai-backend.onrender.com/voice"
BACKEND_BASE_URL = "https://rk-ai-backend.onrender.com"  # Base URL for text endpoint
REQUEST_TIMEOUT = 30  # seconds (increased for slow backend responses)

# Gemini API (for direct fast responses)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEY_BACKUP = os.getenv("GEMINI_API_KEY_BACKUP", "")  # Backup key for failover
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")  # Fast model for low latency
USE_GEMINI_DIRECT = os.getenv("USE_GEMINI_DIRECT", "1") == "1"  # Feature flag

# Groq API (for ultra-fast STT)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
STT_ENGINE = os.getenv("STT_ENGINE", "groq")  # Options: "groq", "google"



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

# Preferred BlueZ adapter (default hci0 on Raspberry Pi)
BLUETOOTH_HCI = os.getenv("BLUETOOTH_HCI", "hci1")

# Offline command whitelist (100 max). Keep short strings for cheap checks.
OFFLINE_COMMANDS = [
    # Greetings and conversational
    "hello", "hi", "hey", "good morning", "good afternoon", "good evening", "good night",
    "how are you", "what's up", "how's it going", "what are you doing",
    "thank you", "thanks", "thank you very much", "many thanks",
    "okay", "ok", "alright", "fine", "sure", "yes", "yeah", "yep", "no", "nope",
    "goodbye", "bye", "see you", "see you later", "take care",
    "nice", "great", "awesome", "cool", "wonderful", "excellent", "perfect",
    "sorry", "excuse me", "pardon me", "my bad",
    
    # Music and media controls
    "play music", "pause music", "resume music", "stop music",
    "next song", "previous song", "skip", "replay",
    "volume up", "volume down", "mute", "unmute", "increase volume", "decrease volume",
    
    # Information queries
    "what's the weather", "weather", "weather today",
    "news", "headlines", "latest news", "today's news",
    "time", "what time is it", "current time",
    "date", "what's the date", "today's date",
    
    # Announcements and alarms
    "announce", "announcement", "make announcement",
    "set alarm", "cancel alarm", "delete alarm", "stop alarm",
    "set timer", "start timer", "cancel timer", "stop timer",
    "set reminder", "remind me",
    
    # System commands
    "battery", "battery level", "battery status",
    "status", "system status",
    "restart", "reboot", "shutdown", "power off",
    "sleep", "wake", "wake up",
    
    # Network and connectivity
    "wifi status", "internet status", "network status",
    "ip address", "my ip", "connection status",
    "connect wifi", "wifi connect", "disconnect wifi",
    "bluetooth status", "open bluetooth", "close bluetooth", "pair bluetooth",
    "ping", "speed test", "test connection",
    
    # Assistant controls
    "who are you", "what's your name", "introduce yourself",
    "help", "help me", "what can you do",
    "commands", "list commands", "available commands",
    "quiet", "be quiet", "silence", "louder", "speak louder",
    
    # Notes and recording
    "save note", "read note", "take note", "note this",
    "record", "start recording", "stop recording",
    
    # LED and hardware controls (if available)
    "led on", "led off", "turn on led", "turn off led",
    "brightness up", "brightness down",
][:100]

# PocketSphinx model path (optional; uses system default if not set)
POCKETSPHINX_MODEL_DIR = os.getenv("POCKETSPHINX_MODEL_DIR", str(DATA_DIR / "pocketsphinx-model"))

# Appwrite (optional; required for auto-slug repair)
APPWRITE_ENDPOINT = os.getenv("APPWRITE_ENDPOINT", "")
APPWRITE_PROJECT_ID = os.getenv("APPWRITE_PROJECT_ID", "")
APPWRITE_API_KEY = os.getenv("APPWRITE_API_KEY", "")
APPWRITE_DB_ID = os.getenv("APPWRITE_DB_ID", "")
APPWRITE_USERS_COLLECTION = os.getenv("APPWRITE_USERS_COLLECTION", "")
