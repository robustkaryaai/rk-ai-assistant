"""Network helpers."""

from __future__ import annotations

import json
import os
import random
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from .config import (
    APPWRITE_API_KEY,
    APPWRITE_DB_ID,
    APPWRITE_ENDPOINT,
    APPWRITE_PROJECT_ID,
    APPWRITE_USERS_COLLECTION,
    BACKEND_BASE_URL,
    BACKEND_URL,
    REQUEST_TIMEOUT,
    SLUG_FILE,
    BLUETOOTH_SPEAKER_MAC,
)


def setup_bluetooth() -> bool:
    """
    Automate Bluetooth connection on startup.
    1. Bring up hci1 (force up).
    2. Connect to configured speaker.
    3. Set as default sink.
    """
    try:
        # 1. Force hci1 up
        print("[bluetooth] Ensuring hci1 is up...", flush=True)
        subprocess.run(["sudo", "hciconfig", "hci1", "up"], check=False)
        time.sleep(1)

        # 2. Connect to speaker
        mac = BLUETOOTH_SPEAKER_MAC
        print(f"[bluetooth] Connecting to speaker {mac}...", flush=True)
        # Use simple timeout with check=False to avoid crashing if already connected
        subprocess.run(["bluetoothctl", "connect", mac], check=False, timeout=10)
        time.sleep(2)
        
        # 3. Set default sink (construct name from MAC)
        # MAC E0:C8... -> bluez_output.E0_C8..._32.1
        # Replace : with _ and append .1 (usually)
        sink_name = f"bluez_output.{mac.replace(':', '_')}.1"
        print(f"[bluetooth] Setting default sink to {sink_name}...", flush=True)
        subprocess.run(["pactl", "set-default-sink", sink_name], check=False)
        
        # 4. Set volume to 15%
        subprocess.run(["pactl", "set-sink-volume", sink_name, "50%"], check=False)
        
        return True
    except Exception as e:
        print(f"[bluetooth] Setup error: {e}", flush=True)
        return False


def is_online(host: str = "1.1.1.1", port: int = 53, timeout: float = 1.5) -> bool:
    """Cheap online check using UDP socket."""
    try:
        socket.setdefaulttimeout(timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
        return True
    except OSError:
        return False


def read_slug() -> tuple[Optional[str], bool]:
    """
    Read slug.txt.
    Returns (slug_string, is_verified_bool).
    """
    path = Path(SLUG_FILE)
    if not path.exists():
        return None, False
    
    lines = path.read_text().strip().splitlines()
    if not lines:
        return None, False
        
    slug = lines[0].strip()
    if not (slug.isdigit() and len(slug) == 9):
        return None, False
        
    verified = False
    if len(lines) > 1:
        verified = (lines[1].strip().lower() == "true")
        
    return slug, verified


def write_slug(slug: str, verified: bool = False) -> None:
    """
    Write slug to slug.txt.
    If verified is True, writes 'true' on second line.
    """
    content = f"{slug}"
    if verified:
        content += "\ntrue"
    Path(SLUG_FILE).write_text(content)


def generate_slug() -> str:
    return f"{random.randint(100000000, 999999999)}"


def post_audio_to_backend(audio_path: Path, slug: str) -> Dict[str, Any]:
    """Send audio file to backend. Returns parsed JSON or {} on error."""
    url = f"{BACKEND_URL}/{slug}"
    try:
        files = {"file": open(audio_path, "rb")}
        try:
            resp = requests.post(url, files=files, timeout=REQUEST_TIMEOUT)
            if resp.ok:
                try:
                    return resp.json()
                except Exception:
                    return {}
        finally:
            files["file"].close()
    except requests.exceptions.Timeout:
        print(f"[network] Backend request timed out after {REQUEST_TIMEOUT}s", flush=True)
        return {"error": "timeout", "message": "Backend request timed out"}
    except Exception as e:
        print(f"[network] Error posting audio: {e}", flush=True)
        return {"error": "network_error", "message": str(e)}
    return {}


def post_text_to_backend(text: str, slug: str) -> Dict[str, Any]:
    """Send transcription text to backend. Returns parsed JSON or {} on error."""
    url = f"{BACKEND_BASE_URL}/text/{slug}"
    payload = {"text": text}
    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        if resp.ok:
            try:
                return resp.json()
            except Exception:
                return {}
        return {"error": "http_error", "message": f"HTTP {resp.status_code}"}
    except requests.exceptions.Timeout:
        print(f"[network] Backend request timed out after {REQUEST_TIMEOUT}s", flush=True)
        return {"error": "timeout", "message": "Backend request timed out"}
    except Exception as e:
        print(f"[network] Error posting text: {e}", flush=True)
        return {"error": "network_error", "message": str(e)}





def fetch_url(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.ok:
            return resp.text
    except Exception:
        return None
    return None


def apply_wifi_credentials(ssid: str, password: str) -> bool:
    """
    Append Wi‑Fi credentials using wpa_cli (avoids rewriting file).
    Requires sudo privileges. Returns True on success.
    """
    try:
        # Add network
        net_id = subprocess.check_output(
            ["sudo", "wpa_cli", "-i", "wlan0", "add_network"],
            timeout=5
        ).decode().strip()

        # Set SSID
        subprocess.check_call(
            ["sudo", "wpa_cli", "-i", "wlan0", "set_network", net_id, "ssid", ssid],
            timeout=5
        )

        # Set PSK
        subprocess.check_call(
            ["sudo", "wpa_cli", "-i", "wlan0", "set_network", net_id, "psk", password],
            timeout=5
        )

        # Enable
        subprocess.check_call(
            ["sudo", "wpa_cli", "-i", "wlan0", "enable_network", net_id],
            timeout=5
        )

        # Save config
        subprocess.check_call(
            ["sudo", "wpa_cli", "-i", "wlan0", "save_config"],
            timeout=5
        )

        return True
    except Exception as e:
        print("Error:", e)
        return False





