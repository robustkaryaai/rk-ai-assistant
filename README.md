# RK AI Pi Client (Raspberry Pi Zero W)

Lightweight Python client for RK voice assistant optimized for Pi Zero W (512MB RAM).

## Features
- Wake word "rk" via PocketSphinx.
- Records speech, sends to RK backend when online, cleans up temp audio.
- Offline fallback with 50 whitelisted commands.
- Music control (mpg123), volume control (amixer), TTS via espeak.
- Bluetooth RFCOMM server to receive Wi‑Fi credentials from the mobile app.
- Weather/news fetch with caching into `weather.json` and `news.json`.

## Setup (Pi OS)
```bash
sudo apt-get update
sudo apt-get install -y python3-pip espeak mpg123 alsa-utils bluez bluez-tools \
    portaudio19-dev python3-dev libbluetooth-dev
pip3 install -r requirements.txt

# Install optional dependencies:
# 1. PocketSphinx (for wake word detection - optional but recommended)
# First install system dependencies:
sudo apt-get install -y swig libpulse-dev libasound2-dev
sudo apt-get install -y python3-dev libsphinxbase-dev libpocketsphinx-dev
pip3 install pocketsphinx

# 2. PyBluez (for Bluetooth Wi-Fi setup - optional)
pip3 install pybluez
# If the above fails, you may need: sudo apt-get install libbluetooth-dev
```

**Note:** Both `pocketsphinx` and `pybluez` are optional. The code will work without them:
- Without `pocketsphinx`: Wake word detection will be disabled (you'll need another way to trigger commands)
- Without `pybluez`: Bluetooth Wi-Fi setup feature will be disabled

PocketSphinx uses system-installed acoustic models by default. If you want to use a custom model, set the `POCKETSPHINX_MODEL_DIR` environment variable.

## Configure
- Put your 9-digit slug in `rk_assistant/slug.txt`.
- Export optional API keys:
  - `WEATHER_API_KEY` (OpenWeather)
  - `NEWS_API_KEY` (NewsAPI)
- Optionally set `POCKETSPHINX_MODEL_DIR` env var if using a custom model (uses system default otherwise).

### Environment variables
Create a `.env` (or export in shell) with:
- `APPWRITE_ENDPOINT` – e.g. `https://cloud.appwrite.io/v1`
- `APPWRITE_PROJECT_ID` – Appwrite project ID
- `APPWRITE_API_KEY` – key with write access to the users collection
- `APPWRITE_DB_ID` – database ID
- `APPWRITE_USERS_COLLECTION` – users collection ID
- `WEATHER_API_KEY` – WeatherAPI.com key
- `NEWS_API_KEY` – NewsAPI.org key
- `POCKETSPHINX_MODEL_DIR` – optional override for PocketSphinx model path
- `BT_CHANNEL` – optional RFCOMM channel (default 3)

Security notes:
- Keep `.env` out of git and set file perms: `chmod 600 .env`.
- Use a minimal-scope Appwrite API key and rotate it if exposure is suspected.
- Prefer storing secrets in a root-owned location and run the service under a non-root user.
- Restrict SSH/Bluetooth access on the Pi; disable password SSH, use keys only.

## Run
```bash
python3 -m rk_assistant.main
```

## Notes
- Bluetooth server listens on RFCOMM channel 3. Payload JSON: `{"ssid":"...","password":"..."}`.
- Temporary recordings saved at `rk_assistant/data/last_command.wav` and deleted after upload.
- Weather/news caches in `rk_assistant/data/weather.json` and `rk_assistant/data/news.json`.


