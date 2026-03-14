"""
BLE Provisioning for RK AI Assistant.

Instead of Wi-Fi AP, this module uses Bluetooth Low Energy (BLE) to receive
Wi-Fi credentials from the companion app. The phone stays on its home Wi-Fi
throughout the entire process - no internet interruption.

Flow:
  1. Pi advertises a BLE GATT service "RK-AI-Provision"
  2. App scans for it, connects, and writes JSON: {"ssid": "...", "password": "..."}
  3. Pi reads the written value, saves credentials via nmcli, and reboots networking.

Uses the `bless` library (pip install bless) for GATT server (peripheral role).
"""

import json
import logging
import asyncio
import threading
import time
import subprocess
import os
import sys

logger = logging.getLogger(__name__)

# ---- BLE / GATT UUIDs (fixed, must match the app) ----
PROVISION_SERVICE_UUID     = "12345678-1234-1234-1234-123456789abc"
CREDENTIALS_CHAR_UUID      = "12345678-1234-1234-1234-123456789abd"  # write
STATUS_CHAR_UUID           = "12345678-1234-1234-1234-123456789abe"  # read/notify

_received_credentials = None
_provision_done = threading.Event()


def _run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def apply_wifi(ssid, password):
    """Save Wi-Fi credentials via nmcli and reboot networking."""
    logger.info(f"[ble-prov] Applying Wi-Fi: {ssid}")
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
        logger.error(f"[ble-prov] Failed to add Wi-Fi: {err}")
        return False

    logger.info(f"[ble-prov] Connecting to {ssid}...")
    _run_cmd(f"sudo nmcli con up '{ssid}'")
    logger.info("[ble-prov] Rebooting...")
    time.sleep(2)
    os.system("sudo reboot")
    return True


async def _run_ble_server(slug, timeout=600):
    """Async BLE GATT server using bless."""
    global _received_credentials

    try:
        from bless import (
            BlessServer,
            BlessGATTCharacteristicProperties,
            GATTAttributePermissions,
        )
    except ImportError:
        logger.error("[ble-prov] `bless` not installed. Run: pip install bless")
        return False

    device_name = f"RK-AI-{slug}"
    logger.info(f"[ble-prov] Starting BLE GATT server: {device_name}")

    server = BlessServer(name=device_name)

    # Add service
    await server.add_new_service(PROVISION_SERVICE_UUID)

    # Writable credentials characteristic
    char_flags = (
        BlessGATTCharacteristicProperties.write |
        BlessGATTCharacteristicProperties.write_without_response
    )
    permissions = GATTAttributePermissions.writeable

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
            data = json.loads(bytes(value).decode("utf-8"))
            ssid = data.get("ssid", "").strip()
            password = data.get("password", "").strip()
            if ssid:
                logger.info(f"[ble-prov] Received credentials for SSID: {ssid}")
                _received_credentials = (ssid, password)
                _provision_done.set()
        except Exception as e:
            logger.error(f"[ble-prov] Failed to parse credentials: {e}")

    server.write_request_func = on_write

    await server.start()
    logger.info(f"[ble-prov] BLE server advertising as '{device_name}'...")

    # Wait for credentials to arrive (with timeout)
    end_time = time.time() + timeout
    while not _provision_done.is_set():
        await asyncio.sleep(1)
        if time.time() > end_time:
            logger.warning("[ble-prov] BLE provisioning timed out.")
            break

    await server.stop()
    return _provision_done.is_set()


def run_ble_provisioning(slug, timeout=600):
    """
    Run BLE provisioning synchronously (blocks until done or timeout).
    Returns True if credentials were received and applied.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        received = loop.run_until_complete(_run_ble_server(slug, timeout))
    finally:
        loop.close()

    if received and _received_credentials:
        ssid, password = _received_credentials
        apply_wifi(ssid, password)
        return True

    logger.warning("[ble-prov] No credentials received. Continuing without provisioning.")
    return False


if __name__ == "__main__":
    from rk_assistant.networking import read_slug
    slug, _ = read_slug()
    run_ble_provisioning(slug or "000000000")
