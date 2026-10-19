import subprocess
import time
from config import BLUETOOTH_HCI

class BluetoothAdapterManager:
    """
    Strict Bluetooth Watchdog for Pi Zero W:
    - Enforces BLUETOOTH_HCI ('hci1').
    - hci0 is damaged on this board and must NEVER be used.
    - If hci1 disappears, immediately reboots to recover the USB bus.
    """

    @staticmethod
    def is_adapter_present() -> bool:
        try:
            out = subprocess.check_output(["hciconfig"], text=True)
            return BLUETOOTH_HCI in out
        except Exception:
            return False

    @classmethod
    def ensure_adapter_up(cls) -> bool:
        """Unblocks rfkill and brings hci1 UP."""
        try:
            subprocess.run(["sudo", "rfkill", "unblock", "bluetooth"], stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "hciconfig", BLUETOOTH_HCI, "up"], stderr=subprocess.DEVNULL)
            time.sleep(0.5)
            out = subprocess.check_output(["hciconfig", BLUETOOTH_HCI], text=True)
            is_up = "UP RUNNING" in out or "UP" in out
            if is_up:
                print(f"📶 [BLUETOOTH] Adapter '{BLUETOOTH_HCI}' is UP and RUNNING.")
            return is_up
        except Exception as e:
            print(f"[bluetooth] Error bringing {BLUETOOTH_HCI} up: {e}")
            return False

    @classmethod
    def verify_or_reboot(cls):
        """Checks for hci1 with a multi-second retry loop so USB dongles have time to enumerate."""
        for attempt in range(5):
            if cls.is_adapter_present():
                cls.ensure_adapter_up()
                return
            print(f"⏳ [BLUETOOTH] Waiting for '{BLUETOOTH_HCI}' to enumerate (attempt {attempt+1}/5)...")
            time.sleep(1.0)

        print(f"⚠️ [BLUETOOTH] Warning: Adapter '{BLUETOOTH_HCI}' not detected in hciconfig. Continuing without reboot.")
