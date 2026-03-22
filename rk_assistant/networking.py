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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

# Global session for better performance and SSL stability
_session = requests.Session()
_last_online_check = 0
_online_cache = False
_retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
)
_adapter = HTTPAdapter(max_retries=_retry_strategy)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)
_session.headers.update({
    "User-Agent": "RK-AI-Assistant/3.0 (RaspberryPi; ZeroW)",
    "Connection": "keep-alive"
})

def is_online() -> bool:
    """
    Check if the system has an active internet connection.
    Caches result for 3 seconds to avoid redundant HTTP calls in the loop.
    """
    global _last_online_check, _online_cache
    if FORCE_OFFLINE:
        return False
        
    # 🚀 Use cache if it's fresh (3 seconds)
    if time.time() - _last_online_check < 3:
        return _online_cache

    try:
        # 1. Quick local check: do we even have an IP?
        output = subprocess.check_output(["hostname", "-I"]).decode().strip()
        if not output:
            _online_cache = False
            _last_online_check = time.time()
            return False
        
        # 2. HTTP Health Check to Backend (The ultimate truth)
        try:
            resp = _session.get(f"{BACKEND_BASE_URL}/health", timeout=3)
            if resp.ok:
                _online_cache = True
                _last_online_check = time.time()
                return True
        except:
            pass

        # 3. Fallback to public DNS targets if backend is down but internet is up
        targets = ["https://1.1.1.1", "https://google.com"]
        for target in targets:
            try:
                _session.head(target, timeout=2)
                _online_cache = True
                _last_online_check = time.time()
                return True
            except:
                continue

        _online_cache = False
        _last_online_check = time.time()
        return False
    except Exception:
        _online_cache = False
        _last_online_check = time.time()
        return False


def get_ip_address() -> str:
    """Returns the primary IP address of the device."""
    try:
        # 1. Quick local check: do we even have an IP?
        output = subprocess.check_output(["hostname", "-I"]).decode().strip()
        if output:
            return output.split()[0] # Return the first one (primary)
    except Exception:
        pass
    return "0.0.0.0"


def wait_for_internet(timeout: int = 60) -> bool:
    """Wait for internet connection for up to timeout seconds."""
    print(f"[network] Waiting {timeout}s for internet connection...", flush=True)
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_online():
            print("[network] Connected to internet!", flush=True)
            return True
        time.sleep(5)
    print("[network] Internet wait timed out.", flush=True)
    return False


def report_state(slug: str, state: str) -> bool:
    """
    Report the current activity state of the assistant to the backend.
    States: 'idle', 'thinking', 'speaking', 'playing', 'listening'
    """
    if not slug or not is_online():
        return False
    try:
        url = f"{BACKEND_BASE_URL}/device/{slug}/state"
        _session.post(url, json={"state": state}, timeout=5)
        return True
    except Exception as e:
        print(f"[network] Failed to report state '{state}': {e}")
        return False


def report_night_mode(slug: str, active: bool) -> bool:
    """
    Report the live night-protocol runtime state to the backend.
    This is separate from the saved user setting.
    """
    if not slug or not is_online():
        return False
    try:
        url = f"{BACKEND_BASE_URL}/device/{slug}/night-mode"
        _session.post(url, json={"active": bool(active)}, timeout=5)
        return True
    except Exception as e:
        print(f"[network] Failed to report night mode '{active}': {e}")
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
            resp = _session.post(url, files=files, timeout=REQUEST_TIMEOUT)
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
        resp = _session.post(url, json=payload, timeout=45)
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
        resp = _session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.ok:
            return resp.text
    except Exception:
        return None
    return None


def apply_wifi_credentials(ssid: str, password: str) -> bool:
    """
    Apply Wi‑Fi credentials using nmcli (NetworkManager).
    Requires sudo privileges. Returns True on success.
    """
    try:
        print(f"[network] Applying Wi-Fi via nmcli: {ssid}", flush=True)
        # Delete existing connection if it exists
        subprocess.run(["sudo", "nmcli", "con", "delete", ssid], capture_output=True)
        
        # Add and connect
        if password:
            cmd = [
                "sudo", "nmcli", "dev", "wifi", "connect", ssid, 
                "password", password, "name", ssid
            ]
        else:
            cmd = [
                "sudo", "nmcli", "dev", "wifi", "connect", ssid, 
                "name", ssid
            ]
            
        result = subprocess.run(cmd, timeout=30, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"[network] Successfully connected to {ssid}", flush=True)
            return True
        else:
            print(f"[network] Failed to connect to {ssid}: {result.stderr}", flush=True)
            return False
            
    except Exception as e:
        print(f"[network] Error applying Wi-Fi via nmcli: {e}", flush=True)
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


def check_network_health():
    """Diagnostic check for network health."""
    online = is_online()
    ip = get_ip_address()
    print(f"[network-health] Online: {online}, IP: {ip}", flush=True)
    
    if not online:
        # Try to ping google
        try:
            subprocess.run(["ping", "-c", "1", "8.8.8.8"], capture_output=True, timeout=2)
            print("[network-health] Ping 8.8.8.8: SUCCESS (DNS might be broken)", flush=True)
        except:
            print("[network-health] Ping 8.8.8.8: FAILED", flush=True)
    return online


def sync_wifi_from_appwrite(slug: str) -> bool:
    """
    Polls the backend for a pending 'set_wifi' command for this slug.
    If found, applies the Wi-Fi and returns True.
    """
    if not is_online():
        return False

    url = f"{BACKEND_BASE_URL}/device/{slug}/commands/pending"
    
    try:
        resp = requests.get(url, timeout=10)
        if resp.ok:
            data = resp.json()
            commands = data.get('commands', [])
            for cmd in commands:
                if cmd.get('command_type') == 'set_wifi':
                    payload = cmd.get('payload', {})
                    new_ssid = payload.get('ssid')
                    new_pass = payload.get('password')
                    
                    if new_ssid:
                        print(f"[network] Found Wi-Fi update command: {new_ssid}", flush=True)
                        
                        # Mark command as complete so it doesn't trigger again
                        cmd_id = cmd.get('$id')
                        try:
                            requests.post(
                                f"{BACKEND_BASE_URL}/device/{slug}/commands/{cmd_id}/complete",
                                json={"result": f"Applying Wi-Fi credentials for {new_ssid} via Setup Hotspot", "success": True},
                                timeout=5
                            )
                        except: pass

                        # Apply credentials
                        success = apply_wifi_credentials(new_ssid, new_pass or "")
                        return success
    except Exception as e:
        print(f"[network] Error syncing Wi-Fi from backend: {e}", flush=True)
    
    return False
