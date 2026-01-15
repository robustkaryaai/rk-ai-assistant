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
)


def setup_bluetooth() -> bool:
    """
    Automate Bluetooth connection on startup.
    1. Bring up hci1 (force up).
    2. Connect to configured speaker (skip if already connected).
    3. Set as default sink.
    """
    try:
        # 1. Check if adapter exists
        print(f"[bluetooth] Checking if {BLUETOOTH_HCI} exists...", flush=True)
        check = subprocess.run(["hciconfig", BLUETOOTH_HCI], capture_output=True, text=True)
        if check.returncode != 0:
            print(f"[bluetooth] CRITICAL ERROR: {BLUETOOTH_HCI} NOT FOUND!", flush=True)
            print("[bluetooth] Triggering automatic reboot in 5 seconds...", flush=True)
            time.sleep(5)
            subprocess.run(["sudo", "reboot"], check=False)
            return False

        # 2. Force adapter up
        print(f"[bluetooth] Ensuring {BLUETOOTH_HCI} is up...", flush=True)
        subprocess.run(["sudo", "hciconfig", BLUETOOTH_HCI, "up"], check=False)
        time.sleep(1)

        # 3. Check if speaker already connected
        mac = BLUETOOTH_SPEAKER_MAC
        info = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True)
        
        if "Connected: yes" in info.stdout:
            print(f"[bluetooth] Speaker {mac} already connected (auto-connected at boot)!", flush=True)
        else:
            # Speaker not connected, attempt connection
            print(f"[bluetooth] Waiting for speaker {mac} to connect...", flush=True)
            
            while True:
                # Try to connect
                subprocess.run(["bluetoothctl", "connect", mac], check=False, timeout=10)
                
                # Verify connection
                info = subprocess.run(["bluetoothctl", "info", mac], capture_output=True, text=True)
                if "Connected: yes" in info.stdout:
                     print(f"[bluetooth] Speaker {mac} connected!", flush=True)
                     break
                
                print("[bluetooth] Speaker not connected, retrying in 5s...", flush=True)
                time.sleep(5)

        time.sleep(2)
        
        # 4. Get Bluetooth sink ID from MAC address with fallback patterns
        mac = BLUETOOTH_SPEAKER_MAC
        mac_underscore = mac.replace(':', '_')
        
        # Try multiple sink name patterns
        sink_patterns = [
            f"bluez_output.{mac_underscore}.1",
            f"bluez_sink.{mac_underscore}.a2dp_sink",
            f"bluez_sink.{mac_underscore}",
            f"bluez_output.{mac_underscore}",
            mac_underscore,  # Partial match
        ]
        
        print(f"[bluetooth] Finding Bluetooth sink for speaker {mac}...", flush=True)
        sink_list = subprocess.run(["pactl", "list", "sinks", "short"], capture_output=True, text=True)
        
        sink_id = None
        sink_name_found = None
        
        # Try each pattern
        for pattern in sink_patterns:
            for line in sink_list.stdout.split('\n'):
                if pattern in line and line.strip():
                    # Extract sink ID (first column)
                    parts = line.split()
                    if len(parts) >= 2:
                        sink_id = parts[0]
                        sink_name_found = parts[1]
                        print(f"[bluetooth] ✓ Found sink '{sink_name_found}' with ID: {sink_id}", flush=True)
                        break
            if sink_id:
                break
        
        if not sink_id:
            # Try dynamic discovery - find any bluez sink
            print(f"[bluetooth] Searching for any bluez sink...", flush=True)
            for line in sink_list.stdout.split('\n'):
                if 'bluez' in line.lower() and line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        sink_id = parts[0]
                        sink_name_found = parts[1]
                        print(f"[bluetooth] ✓ Found bluez sink: {sink_name_found} (ID: {sink_id})", flush=True)
                        break
        
        if not sink_id:
            print(f"[bluetooth] WARNING: Could not find Bluetooth sink for {mac}", flush=True)
            print(f"[bluetooth] Available sinks:", flush=True)
            print(sink_list.stdout, flush=True)
            
            # Continue anyway - PulseAudio might auto-route
            return True  # Don't fail completely, audio might still work
        
        # 5. Unsuspend sink if suspended
        if "SUSPENDED" in sink_list.stdout:
            print(f"[bluetooth] Sink is SUSPENDED, unsuspending...", flush=True)
            subprocess.run(["pactl", "suspend-sink", sink_id, "0"], check=False)
            time.sleep(1)
            print(f"[bluetooth] Sink unsuspended!", flush=True)
        else:
            print(f"[bluetooth] Sink is active", flush=True)
        
        # 6. Set as default sink
        print(f"[bluetooth] Setting default sink to ID {sink_id}...", flush=True)
        subprocess.run(["pactl", "set-default-sink", sink_id], check=False)
        
        # 7. Set volume to 100%
        subprocess.run(["pactl", "set-sink-volume", sink_id, "100%"], check=False)
        print(f"[bluetooth] Volume set to 100%", flush=True)
        
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


def send_to_backend_async(text: str, slug: str) -> None:
    """
    Send command to backend asynchronously (fire and forget).
    Simple wrapper for voice_simple.py compatibility.
    """
    import threading
    
    def _send():
        try:
            post_text_to_backend(text, slug)
        except Exception as e:
            print(f"[network] Async backend error: {e}", flush=True)
    
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def check_network_health() -> None:
    """
    Log current network latency and signal strength (if wifi).
    Designed to be fast and non-blocking (informative only).
    """
    try:
        # 1. Ping Check (Google DNS)
        # -c 1 = count 1, -W 1 = timeout 1s
        res = subprocess.run(["ping", "-c", "1", "-W", "1", "8.8.8.8"], 
                           capture_output=True, text=True)
        
        latency = "Timeout"
        if res.returncode == 0:
            # Parse output: "time=14.2 ms"
            import re
            match = re.search(r"time=([\d\.]+)", res.stdout)
            if match:
                latency = f"{match.group(1)}ms"
        
        # 2. Wifi Signal Check (if wlan0 is active)
        signal = "N/A"
        try:
            # iwconfig wlan0 | grep "Signal level"
            # Output: Link Quality=70/70  Signal level=-40 dBm
            iw = subprocess.run(["iwconfig", "wlan0"], capture_output=True, text=True)
            if iw.returncode == 0:
                match = re.search(r"Signal level=(-\d+)", iw.stdout)
                if match:
                    signal = f"{match.group(1)}dBm"
        except:
            pass
            
        print(f"[network] Status 📶 | Latency: {latency} | Signal: {signal}", flush=True)
        
    except Exception as e:
        print(f"[network] Health check failed: {e}", flush=True)


def setup_microphone_volume() -> None:
    """
    Force microphone capture volume to 100% using amixer.
    Tried 'Capture' first, then 'Mic'.
    """
    try:
        print("[audio] Setting hardware microphone gain to 100%...", flush=True)
        # Try 'Capture' (common for USB mics)
        res = subprocess.run(["amixer", "sset", "Capture", "100%"], 
                           capture_output=True, text=True)
        if res.returncode != 0:
            # Fallback to 'Mic'
            res = subprocess.run(["amixer", "sset", "Mic", "100%"], 
                               capture_output=True, text=True)
            
        if res.returncode == 0:
            print("[audio] Hardware gain set! 🎚️", flush=True)
        else:
            print(f"[audio] Warning: Could not set volume: {res.stderr.strip()}", flush=True)
            
    except Exception as e:
        print(f"[audio] Volume setup error: {e}", flush=True)




