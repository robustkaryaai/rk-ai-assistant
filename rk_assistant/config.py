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
# Load .env file
# Priority: Project Root -> Package Dir
# We print which one is loaded to avoid confusion
_project_root_env = BASE_DIR.parent / ".env"
_package_env = BASE_DIR / ".env"

if _project_root_env.exists():
    _target_env = _project_root_env
    print(f"[config] Loading .env from Project Root: {_target_env}")
elif _package_env.exists():
    _target_env = _package_env
    print(f"[config] Loading .env from Package Dir: {_target_env}")
else:
    _target_env = None
    print("[config] Warning: No .env file found.")

if _target_env:
    try:
        with open(_target_env, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ[key] = value
    except Exception as e:
        print(f"[config] Error reading .env: {e}")

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
WAKE_WORDS = [
    # Core RK forms
    "rk", "r k", "r.k.", "ark", "arc",

    # Direct phonetic variations
    "arky", "arkey", "arkie", "arkay", "arke", "arki",
    "archi", "archie", "archai",

    # Vowel-expanded helpers (improves STT capture)
    "arika", "aarika", "arka", "aar key", "are key", "arr key",
    "ar kee", "aar kee", "our key", "our k",

    # Indian-accent realistic matches
    "aarki", "aarky", "aari", "aarav",
    "aarti", "arti", "arty", "artie", "aarty",

    # Close sound-alike names/words
    "archana", "arya", "aryan", "rishi", "rushi", "ruby",

    # RK-style alternate assistant names
    "rocky", "rocket",

    # Rare but possible STT confusions
    "earthy", "arctic", "arcade", "arise", "aapke"
]


# Microphone configuration for live STT
_mic_env = os.getenv("MIC_DEVICE_INDEX")
MIC_DEVICE_INDEX = int(_mic_env) if _mic_env is not None else None
MIC_DEVICE_NAME = os.getenv("MIC_DEVICE_NAME", None)
MIC_SAMPLE_RATE = int(os.getenv("MIC_SAMPLE_RATE", str(SAMPLE_RATE)))
GTTS_ENABLE = os.getenv("GTTS_ENABLE", "1") == "1"
GTTS_PLAYBACK_TIMEOUT = int(os.getenv("GTTS_PLAYBACK_TIMEOUT", "120"))
GTTS_LANG = os.getenv("GTTS_LANG", "en")
GTTS_TLD = os.getenv("GTTS_TLD", "co.in")
MPG123_OUTPUT = os.getenv("MPG123_OUTPUT", "pulse")

# Piper TTS (offline, high-quality voice synthesis)
PIPER_EXECUTABLE = os.getenv("PIPER_EXECUTABLE", "/usr/local/bin/piper")
PIPER_VOICE_MODEL = os.getenv(
    "PIPER_VOICE_MODEL", 
    str(Path.home() / ".local/share/piper/voices/en_US-lessac-medium.onnx")
)

# Backend
BACKEND_URL = "https://rk-ai-backend.onrender.com/voice"
BACKEND_BASE_URL = "https://rk-ai-backend.onrender.com"  # Base URL for text endpoint
REQUEST_TIMEOUT = 180  # seconds (increased for slow backend/network)

# Gemini API (for direct fast responses)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEY_BACKUP = os.getenv("GEMINI_API_KEY_BACKUP", "")  # Backup key for failover
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-3-12b-it")  # Fast model for low latency
USE_GEMINI_DIRECT = os.getenv("USE_GEMINI_DIRECT", "1") == "1"  # Feature flag

# Groq API (for ultra-fast STT)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Gemini Model Configuration₹
GEMINI_MODEL_PRIMARY = os.getenv("GEMINI_MODEL_PRIMARY", "gemini-2.5-flash")  # Flash for fast intent routing
GEMINI_MODEL_FALLBACK = os.getenv("GEMINI_MODEL_FALLBACK", "gemma-3-4b-it")  # Tiny Gemma fallback if flash fails
STT_ENGINE = os.getenv("STT_ENGINE", "google")  # Options: "groq", "google"



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
BLUETOOTH_SPEAKER_MAC = os.getenv("BLUETOOTH_SPEAKER_MAC", "D0:78:1D:4F:F4:1E")

# Preferred BlueZ adapter (default hci0 on Raspberry Pi)
BLUETOOTH_HCI = os.getenv("BLUETOOTH_HCI", "hci1")

# Feature Toggles
MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "1") == "1"
MUTE_MODE = os.getenv("MUTE_MODE", "0") == "1"
ROUTINES_SYNC_URL = f"{BACKEND_BASE_URL}/routines"

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
    
    # Music    # Music controls
    "play music", "stop music", "pause music", "resume music",
    "play again", "replay", "restart song", "repeat",
    "volume up", "volume down", "mute", "unmute",
    "stop", "pause", "quiet", "shut up", "silence", "exit",
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
    "rk update", "rk shutdown", "rk reboot", "rk restart",
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

# Self-Diagnosis Configuration
# Disabled to stop interruptions during backend outage
SELF_DIAGNOSIS_ENABLED = False 
# SELF_DIAGNOSIS_ENABLED = os.getenv("SELF_DIAGNOSIS_ENABLED", "1") == "1"
DIAGNOSIS_COOLDOWN_SECONDS = int(os.getenv("DIAGNOSIS_COOLDOWN_SECONDS", "300"))  # 5 minutes
AUTO_APPLY_FIXES = os.getenv("AUTO_APPLY_FIXES", "1") == "1"  # Automatically apply fixes after testing
ERROR_THRESHOLD_CRITICAL = int(os.getenv("ERROR_THRESHOLD_CRITICAL", "1"))  # 1 critical error triggers diagnosis
ERROR_THRESHOLD_MAJOR = int(os.getenv("ERROR_THRESHOLD_MAJOR", "3"))  # 3 major errors trigger diagnosis
ERROR_THRESHOLD_MINOR = int(os.getenv("ERROR_THRESHOLD_MINOR", "10"))  # 10 minor errors trigger diagnosis
