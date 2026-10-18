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
    def verify_or_reboot(cls):
        if not cls.is_adapter_present():
            print(f"🚨 [WATCHDOG] Fatal: Adapter '{BLUETOOTH_HCI}' is missing! Re-initializing system...")
            subprocess.run(["sudo", "reboot"])
            exit(1)
