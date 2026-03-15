"""
BLE Provisioning for RK AI Assistant.

Uses Bluetooth Low Energy (BLE) GATT server to receive Wi-Fi credentials
from the companion app. The phone stays on home Wi-Fi throughout - no
internet interruption, no hotspot needed.

Uses `bless` library — must be installed in venv: venv/bin/pip install bless
"""

import json
import asyncio
import threading
import time
import subprocess
import os

# BLE / GATT UUIDs — must match WifiSetup.js in the app
PROVISION_SERVICE_UUID = "12345678-1234-1234-1234-123456789abc"
CREDENTIALS_CHAR_UUID  = "12345678-1234-1234-1234-123456789abd"

_received_credentials = None
_provision_done = threading.Event()


def _run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _get_ble_adapter():
    """Return the name of the first UP BLE adapter (e.g. hci1)."""
    rc, out, _ = _run_cmd("hciconfig")
    # Find all 'hciX:' blocks and return the first one that is UP
    import re
    blocks = re.split(r'\n(?=hci\d+:)', out)
    for block in blocks:
        m = re.match(r'(hci\d+):', block)
        if m and 'UP' in block:
            return m.group(1)
    return None


def apply_wifi(ssid, password):
    """Save Wi-Fi credentials via nmcli and reboot."""
    print(f"[ble-prov] Applying Wi-Fi: {ssid}", flush=True)
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
        print(f"[ble-prov] ERROR adding Wi-Fi: {err}", flush=True)
        return False

    print(f"[ble-prov] Connecting to {ssid}...", flush=True)
    _run_cmd(f"sudo nmcli con up '{ssid}'")
    print("[ble-prov] Rebooting in 3s...", flush=True)
    time.sleep(3)
    os.system("sudo reboot")
    return True


async def _run_ble_server(slug, timeout=600):
    """Async BLE GATT server using bless, binding to the first UP adapter."""
    global _received_credentials

    try:
        from bless import BlessServer
    except Exception as e:
        print(f"[ble-prov] ERROR importing bless: {e}", flush=True)
        return False

    adapter = _get_ble_adapter()
    print(f"[ble-prov] Using BLE adapter: {adapter}", flush=True)

    device_name = f"RK-AI-{slug}"
    print(f"[ble-prov] Starting BLE GATT server as: {device_name}", flush=True)

    # Pass adapter to BlessServer if supported (bless >=0.3 supports it)
    try:
        server = BlessServer(name=device_name, adapter=adapter)
    except TypeError:
        server = BlessServer(name=device_name)

    try:
        await server.add_new_service(PROVISION_SERVICE_UUID)

        # In older bless versions, properties and permissions might not be exported as enums.
        # We use the raw bluez integers instead:
        # Properties: write (0x08) | write-without-response (0x04)
        char_flags = 0x08 | 0x04 
        # Permissions: writable (0x02)
        permissions = 0x02

        await server.add_new_characteristic(
            PROVISION_SERVICE_UUID,
            CREDENTIALS_CHAR_UUID,
            char_flags,
            None,
            permissions,
        )

        def on_write(characteristic, value, **kwargs):
            global _received_credentials
            try:
                raw = bytes(value).decode("utf-8")
                data = json.loads(raw)
                ssid = data.get("ssid", "").strip()
                password = data.get("password", "").strip()
                if ssid:
                    print(f"[ble-prov] Received Wi-Fi credentials for SSID: {ssid}", flush=True)
                    _received_credentials = (ssid, password)
                    _provision_done.set()
            except Exception as e:
                print(f"[ble-prov] ERROR parsing credentials: {e}", flush=True)

        server.write_request_func = on_write

        await server.start()
        print(f"[ble-prov] ✓ BLE server advertising as '{device_name}' — waiting for app...", flush=True)

        end_time = time.time() + timeout
        while not _provision_done.is_set():
            await asyncio.sleep(1)
            if time.time() > end_time:
                print("[ble-prov] Timed out waiting for credentials.", flush=True)
                break

        await server.stop()

    except Exception as e:
        print(f"[ble-prov] GATT server error: {e}", flush=True)
        return False

    return _provision_done.is_set()


def run_ble_provisioning(slug, timeout=600):
    """
    Run BLE provisioning (blocks until done or timeout).
    Called in a daemon thread by main.py on first boot.
    """
    print(f"[ble-prov] Starting for slug: {slug}", flush=True)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        received = loop.run_until_complete(_run_ble_server(slug, timeout))
    except Exception as e:
        print(f"[ble-prov] Fatal error: {e}", flush=True)
        received = False
    finally:
        loop.close()

    if received and _received_credentials:
        ssid, password = _received_credentials
        apply_wifi(ssid, password)
        return True

    print("[ble-prov] No credentials received. Continuing without provisioning.", flush=True)
    return False


if __name__ == "__main__":
    from rk_assistant.networking import read_slug
    slug, _ = read_slug()
    run_ble_provisioning(slug or "000000000")
