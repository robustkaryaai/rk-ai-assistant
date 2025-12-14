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
)


def is_online(host: str = "1.1.1.1", port: int = 53, timeout: float = 1.5) -> bool:
    """Cheap online check using UDP socket."""
    try:
        socket.setdefaulttimeout(timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
        return True
    except OSError:
        return False


def read_slug() -> Optional[str]:
    path = Path(SLUG_FILE)
    if not path.exists():
        return None
    slug = path.read_text().strip()
    if slug and slug.isdigit() and len(slug) == 9:
        return slug
    return None


def write_slug(slug: str) -> None:
    Path(SLUG_FILE).write_text(slug)


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
    url = f"{BACKEND_URL}/{slug}"
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


def create_appwrite_user(slug: str) -> bool:
    """Create user record in Appwrite. Returns True on success."""
    required = [
        APPWRITE_ENDPOINT,
        APPWRITE_PROJECT_ID,
        APPWRITE_API_KEY,
        APPWRITE_DB_ID,
        APPWRITE_USERS_COLLECTION,
    ]
    if not all(required):
        return False

    url = f"{APPWRITE_ENDPOINT}/databases/{APPWRITE_DB_ID}/collections/{APPWRITE_USERS_COLLECTION}/documents"
    headers = {
        "X-Appwrite-Project": APPWRITE_PROJECT_ID,
        "X-Appwrite-Key": APPWRITE_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "documentId": slug,
        "data": {
            "slug": slug,
            "subscription": "false",
            "name_of_device": f"RK AI {slug}",
            "storageUsing": "supabase",
        },
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        return resp.ok
    except Exception:
        return False


def validate_slug_with_backend(audio_path: Path, slug: str) -> Dict[str, Any]:
    """Send probe audio to backend to check slug validity."""
    return post_audio_to_backend(audio_path, slug)


