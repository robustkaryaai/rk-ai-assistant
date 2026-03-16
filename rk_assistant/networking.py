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
    BLUETOOTH_HCI,
    FORCE_OFFLINE,
)

def get_ip_address():
    """Get current IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def is_online(host: str = "8.8.8.8", port: int = 53, timeout: float = 3.0) -> bool:
    """Cheap online check using UDP socket. Fakes offline if FORCE_OFFLINE is True."""
    if FORCE_OFFLINE:
        return False
    try:
        socket.setdefaulttimeout(timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
        return True
    except OSError:
        return False


def wait_for_internet(max_minutes: float = 2.0) -> bool:
    """Wait for internet connection for up to max_minutes."""
    print(f"[network] Waiting {max_minutes}m for internet connection...", flush=True)
    start_time = time.time()
    while time.time() - start_time < (max_minutes * 60):
        if is_online():
            print("[network] Connected to internet!", flush=True)
            return True
        time.sleep(5)
    print("[network] Internet wait timed out.", flush=True)
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
        resp = requests.post(url, json=payload, timeout=45)
        if resp.ok:
            try:
                return resp.json()
            except Exception:
                return {}
        return {"error": "http_error", "message": f"HTTP {resp.status_code}"}
    except requests.exceptions.Timeout:
        print(f"[network] Backend request timed out after 45s", flush=True)
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
            ["sudo", "wpa_cli", "-i", "wlan0", "set_network", net_id, "ssid", f'"{ssid}"'],
            timeout=5
        )

        # Set PSK
        if password:
            subprocess.check_call(
                ["sudo", "wpa_cli", "-i", "wlan0", "set_network", net_id, "psk", f'"{password}"'],
                timeout=5
            )
        else:
            subprocess.check_call(
                ["sudo", "wpa_cli", "-i", "wlan0", "set_network", net_id, "key_mgmt", "NONE"],
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
        print(f"[network] Error applying Wi-Fi: {e}", flush=True)
        return False


def try_join_setup_hotspot(ssid="RK-AI-SETUP", password="rkaisetup"):
    """
    Attempts to join the phone's setup hotspot using nmcli.
    """
    print(f"[network] Attempting to join setup hotspot '{ssid}'...", flush=True)
    try:
        # 1. Use nmcli to try and join the hotspot
        # This is very robust on Pi OS with NetworkManager
        cmd = ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", password]
        subprocess.run(cmd, timeout=20, capture_output=True)
        return is_online()
    except Exception as e:
        print(f"[network] Error joining setup hotspot: {e}", flush=True)
        return False


def sync_wifi_from_appwrite(slug: str) -> bool:
    """
    Polls Appwrite for a 'wifi_update' document for this slug.
    If found, applies the Wi-Fi and returns True.
    """
    if not is_online():
        return False

    url = f"{APPWRITE_ENDPOINT}/databases/{APPWRITE_DB_ID}/collections/{APPWRITE_USERS_COLLECTION}/documents"
    headers = {
        "X-Appwrite-Project": APPWRITE_PROJECT_ID,
        "X-Appwrite-Key": APPWRITE_API_KEY,
    }
    params = {
        "queries[]": f'equal("slug", "{slug}")'
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.ok:
            data = resp.json()
            if data.get("total", 0) > 0:
                doc = data["documents"][0]
                # Look for a pending wifi update
                new_ssid = doc.get("wifi_ssid_update")
                new_pass = doc.get("wifi_pass_update")
                
                if new_ssid:
                    print(f"[network] Found Wi-Fi update: {new_ssid}", flush=True)
                    # Apply and clear the update field in Appwrite
                    success = apply_wifi_credentials(new_ssid, new_pass or "")
                    if success:
                        # Clear the update fields so we don't reboot forever
                        update_url = f"{url}/{doc['$id']}"
                        requests.patch(update_url, headers=headers, json={
                            "wifi_ssid_update": "",
                            "wifi_pass_update": ""
                        }, timeout=5)
                        return True
    except Exception as e:
        print(f"[network] Error syncing Wi-Fi from Appwrite: {e}", flush=True)
    
    return False
