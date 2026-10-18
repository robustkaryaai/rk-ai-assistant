import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Device Slug Identifier
SLUG_FILE = BASE_DIR / "slug.txt"
DEFAULT_SLUG = "000000000"
if SLUG_FILE.exists():
    DEVICE_SLUG = SLUG_FILE.read_text().strip() or DEFAULT_SLUG
else:
    DEVICE_SLUG = os.getenv("DEVICE_SLUG", DEFAULT_SLUG)

# Backend (RK_AI_HOME) Configuration
# Default backend URL on Render
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "https://rk-ai-backend.onrender.com").rstrip("/")
APPWRITE_ENDPOINT = os.getenv("APPWRITE_ENDPOINT", "")
APPWRITE_PROJECT_ID = os.getenv("APPWRITE_PROJECT_ID", "")
APPWRITE_API_KEY = os.getenv("APPWRITE_API_KEY", "")
APPWRITE_DB_ID = os.getenv("APPWRITE_DB_ID", "")
APPWRITE_USERS_COLLECTION = os.getenv("APPWRITE_USERS_COLLECTION", "")

# Hardware: Strict hci1 & Speaker Pinning
# Note: hci0 is damaged on this hardware; hci1 is mandatory.
BLUETOOTH_HCI = "hci1"
BLUETOOTH_SPEAKER_MAC = os.getenv("BLUETOOTH_SPEAKER_MAC", "D0:78:1D:4F:F4:1E").strip()
BT_CHANNEL = int(os.getenv("BT_CHANNEL", "3"))
DEVICE_NAME = f"RK-AI-{DEVICE_SLUG}"

# Audio Settings
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
RECORDING_PATH = BASE_DIR / "data" / "last_command.wav"
AUDIO_CACHE_DIR = BASE_DIR / "data" / "audio_cache"

# Polling Intervals (Seconds)
MAINTENANCE_POLL_INTERVAL = 60
COMMAND_POLL_INTERVAL = 5
WATCHDOG_CHECK_INTERVAL = 30
