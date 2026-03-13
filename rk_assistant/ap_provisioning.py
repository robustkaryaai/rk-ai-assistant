"""
AP Provisioning Mode for RK AI Assistant.

If the device has no working internet connection on boot, this module:
1. Creates a Wi-Fi Access Point named "RK-AI-{slug}" (password: rkaisetup)
2. Runs a simple HTTP server at 192.168.4.1:80
3. Waits for a POST /setup with { "ssid": "...", "password": "..." }
4. Saves credentials via nmcli, tears down the AP, and reboots networking

The app connects the phone to this hotspot and POSTs credentials.
No Bluetooth needed. Works on 100% of phones.
"""

import json
import os
import subprocess
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from .networking import read_slug

AP_IP = "192.168.4.1"
AP_PORT = 80
AP_SSID_PREFIX = "RK-AI-"
AP_PASSWORD = "rkaisetup"
SETUP_DONE = threading.Event()
RECEIVED_SSID = None
RECEIVED_PASSWORD = None


class ProvisioningHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for Wi-Fi credential provisioning."""

    def log_message(self, format, *args):
        print(f"[ap-http] {self.address_string()} - {format % args}", flush=True)

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"status": "waiting", "device": "rk-ai"}).encode())
        else:
            # Serve a minimal HTML form as fallback (browser-based provisioning)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self._send_cors_headers()
            self.end_headers()
            html = """<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RK AI Setup</title>
<style>body{font-family:sans-serif;background:#111;color:#fff;padding:32px;max-width:400px;margin:auto}
input{width:100%;padding:12px;margin:8px 0 16px;background:#222;border:1px solid #444;color:#fff;border-radius:8px;box-sizing:border-box}
button{width:100%;padding:14px;background:#6366f1;color:#fff;border:none;border-radius:8px;font-size:16px;cursor:pointer}
h1{margin-bottom:24px}</style></head>
<body><h1>📶 RK AI Wi-Fi Setup</h1>
<form method="POST" action="/setup">
<label>Wi-Fi Network Name (SSID)</label><input name="ssid" required placeholder="Your Wi-Fi name">
<label>Password</label><input name="password" type="password" placeholder="Wi-Fi password">
<button type="submit">Connect RK AI to Wi-Fi</button>
</form></body></html>"""
            self.wfile.write(html.encode())

    def do_POST(self):
        global RECEIVED_SSID, RECEIVED_PASSWORD
        if self.path != "/setup":
            self.send_response(404)
            self.end_headers()
            return

        try:
            content_type = self.headers.get("Content-Type", "")
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")

            if "application/json" in content_type:
                data = json.loads(body)
                ssid = data.get("ssid", "").strip()
                password = data.get("password", data.get("pass", "")).strip()
            else:
                # Form-encoded fallback
                from urllib.parse import parse_qs
                params = parse_qs(body)
                ssid = params.get("ssid", [""])[0].strip()
                password = params.get("password", [""])[0].strip()

            if not ssid:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "ssid required"}).encode())
                return

            print(f"[ap] Received Wi-Fi credentials for SSID: {ssid}", flush=True)
            RECEIVED_SSID = ssid
            RECEIVED_PASSWORD = password

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "message": "Credentials received! RK AI is connecting to your Wi-Fi and will restart."
            }).encode())

            # Signal main thread to apply and reboot
            SETUP_DONE.set()

        except Exception as e:
            print(f"[ap] Error handling POST: {e}", flush=True)
            self.send_response(500)
            self.end_headers()


def _run_cmd(cmd, check=False):
    """Run a shell command, return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{result.stderr}")
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_internet(timeout=5):
    """Return True if device has internet connectivity."""
    try:
        rc, _, _ = _run_cmd(f"ping -c 1 -W {timeout} 8.8.8.8")
        return rc == 0
    except Exception:
        return False


def start_ap(slug):
    """Create a Wi-Fi Access Point using nmcli."""
    ssid = f"{AP_SSID_PREFIX}{slug}"
    print(f"[ap] Creating hotspot: SSID={ssid}  Password={AP_PASSWORD}", flush=True)

    # Delete any previous hotspot connection
    _run_cmd("sudo nmcli con delete 'rk-ai-hotspot' 2>/dev/null || true")

    # Create AP
    rc, out, err = _run_cmd(
        f"sudo nmcli con add type wifi ifname wlan0 con-name rk-ai-hotspot autoconnect no "
        f"ssid '{ssid}' mode ap ipv4.method shared "
        f"wifi-sec.key-mgmt wpa-psk wifi-sec.psk '{AP_PASSWORD}'"
    )
    if rc != 0:
        print(f"[ap] nmcli add error: {err}", flush=True)
        raise RuntimeError("Could not create hotspot")

    rc, out, err = _run_cmd("sudo nmcli con up rk-ai-hotspot")
    if rc != 0:
        print(f"[ap] nmcli up error: {err}", flush=True)
        raise RuntimeError("Could not bring up hotspot")

    print(f"[ap] Hotspot '{ssid}' is up. Waiting for phone...", flush=True)


def stop_ap():
    """Bring down and delete the AP connection."""
    _run_cmd("sudo nmcli con down rk-ai-hotspot 2>/dev/null || true")
    _run_cmd("sudo nmcli con delete rk-ai-hotspot 2>/dev/null || true")
    print("[ap] Hotspot stopped.", flush=True)


def apply_wifi_and_reboot(ssid, password):
    """Save Wi-Fi credentials and restart networking (or reboot)."""
    print(f"[ap] Applying Wi-Fi: {ssid}", flush=True)

    # Delete any old connection with same SSID to avoid conflicts
    _run_cmd(f"sudo nmcli con delete '{ssid}' 2>/dev/null || true")

    if password:
        rc, _, err = _run_cmd(
            f"sudo nmcli con add type wifi ifname wlan0 con-name '{ssid}' ssid '{ssid}' "
            f"wifi-sec.key-mgmt wpa-psk wifi-sec.psk '{password}' autoconnect yes"
        )
    else:
        rc, _, err = _run_cmd(
            f"sudo nmcli con add type wifi ifname wlan0 con-name '{ssid}' ssid '{ssid}' autoconnect yes"
        )

    if rc != 0:
        print(f"[ap] Failed to add Wi-Fi connection: {err}", flush=True)
        return False

    stop_ap()
    time.sleep(1)

    print(f"[ap] Connecting to {ssid}...", flush=True)
    rc, _, err = _run_cmd(f"sudo nmcli con up '{ssid}'")
    if rc != 0:
        print(f"[ap] Could not connect to {ssid}: {err} — rebooting to retry", flush=True)

    # Reboot to ensure clean start
    print("[ap] Rebooting...", flush=True)
    time.sleep(2)
    os.system("sudo reboot")
    return True


def run_ap_provisioning(slug):
    """
    Full AP provisioning flow.
    Blocks until credentials are received or max_wait exceeded.
    Returns True if credentials were received and applied, False otherwise.
    """
    from .config import FORCE_OFFLINE
    if str(FORCE_OFFLINE).lower() == 'true' or FORCE_OFFLINE is True:
        print(f"[ap] Dev Mode: Bypassing Hotspot for slug {slug} to prevent SSH drop", flush=True)
        return False

    print(f"[ap] Starting AP provisioning mode for slug: {slug}", flush=True)

    try:
        start_ap(slug)
    except Exception as e:
        print(f"[ap] Could not start hotspot: {e}", flush=True)
        print("[ap] Falling back — continuing without provisioning", flush=True)
        return False

    # Give AP time to come up
    time.sleep(3)

    # Start HTTP server
    server = HTTPServer(("0.0.0.0", AP_PORT), ProvisioningHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"[ap] HTTP server running at http://{AP_IP}:{AP_PORT}", flush=True)

    # Wait up to 10 minutes for credentials
    MAX_WAIT = 600
    received = SETUP_DONE.wait(timeout=MAX_WAIT)

    server.shutdown()

    if received and RECEIVED_SSID:
        apply_wifi_and_reboot(RECEIVED_SSID, RECEIVED_PASSWORD or "")
        return True
    else:
        print("[ap] No credentials received within timeout. Continuing with existing config.", flush=True)
        stop_ap()
        return False


if __name__ == "__main__":
    slug, _ = read_slug()
    run_ap_provisioning(slug or "000000000")
