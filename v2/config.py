import os
import random
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Device Slug Identifier
# Checks v2/slug.txt first, then falls back to rk_assistant/slug.txt from v1
SLUG_FILE = BASE_DIR / "slug.txt"
V1_SLUG_FILE = BASE_DIR.parent / "rk_assistant" / "slug.txt"

def get_device_slug() -> str:
    # 1. Environment variable
    env_slug = os.getenv("DEVICE_SLUG", "").strip()
    if env_slug and len(env_slug) == 9 and env_slug.isdigit():
        return env_slug

    # 2. v2/slug.txt
    if SLUG_FILE.exists():
        slug = SLUG_FILE.read_text().strip().splitlines()[0].strip()
        if len(slug) == 9 and slug.isdigit() and slug != "000000000":
            return slug

    # 3. Inherit from v1 (rk_assistant/slug.txt) if connected before
    if V1_SLUG_FILE.exists():
        slug = V1_SLUG_FILE.read_text().strip().splitlines()[0].strip()
        if len(slug) == 9 and slug.isdigit() and slug != "000000000":
            # Copy over to v2 so v2 maintains it
            SLUG_FILE.write_text(slug)
            return slug

    # 4. If no valid slug exists, generate a valid random 9-digit slug
    new_slug = str(random.randint(100000000, 999999999))
    SLUG_FILE.write_text(new_slug)
    return new_slug

DEVICE_SLUG = get_device_slug()

# Backend (RK_AI_HOME) Configuration
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
