import subprocess
import time
from config import BLUETOOTH_HCI, BLUETOOTH_SPEAKER_MAC

class BluetoothAdapterManager:
    """
    Lightweight, Non-Intrusive Bluetooth Watchdog for Pi Zero W:
    - Only checks speaker connectivity state via fast lightweight query.
    - Does NOT repeatedly run 'rfkill unblock' or 'sudo hciconfig up' unless adapter is down.
    - Zero spam, zero mic/STT stutter.
    """

    _is_up_cached: bool = False

    @staticmethod
    def is_speaker_connected() -> bool:
        """Fast check if the configured speaker MAC is connected."""
        if not BLUETOOTH_SPEAKER_MAC:
            return True
        try:
            res = subprocess.run(
                ["bluetoothctl", "info", BLUETOOTH_SPEAKER_MAC],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2.0
            )
            return "Connected: yes" in res.stdout
        except Exception:
            return True  # Avoid blocking voice loop on timeout

    @staticmethod
    def is_adapter_present() -> bool:
        try:
            out = subprocess.check_output(["hciconfig", BLUETOOTH_HCI], stderr=subprocess.DEVNULL, text=True)
            return "UP" in out or "RUNNING" in out
        except Exception:
            return False

    @classmethod
    def ensure_adapter_up(cls) -> bool:
        """Brings hci1 UP only once on startup or if down."""
        if cls._is_up_cached and cls.is_adapter_present():
            return True

        try:
            subprocess.run(["sudo", "rfkill", "unblock", "bluetooth"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            subprocess.run(["sudo", "hciconfig", BLUETOOTH_HCI, "up"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            time.sleep(0.3)
            out = subprocess.check_output(["hciconfig", BLUETOOTH_HCI], stderr=subprocess.DEVNULL, text=True)
            is_up = "UP" in out or "RUNNING" in out
            if is_up:
                cls._is_up_cached = True
                print(f"📶 [BLUETOOTH] Adapter '{BLUETOOTH_HCI}' is UP and RUNNING.")
            return is_up
        except Exception as e:
            return False

    @classmethod
    def verify_or_reboot(cls):
        """
        Lightweight check:
        1. If adapter is already UP, skip all hciconfig/rfkill execution.
        2. Only verify speaker connection quietly.
        """
        # If adapter is UP, no need to touch hciconfig or rfkill at all!
        if cls.is_adapter_present():
            cls._is_up_cached = True
            # Quietly check speaker; reconnect in background if needed
            if not cls.is_speaker_connected():
                print(f"⚠️ [BLUETOOTH] Speaker disconnected. Reconnecting to {BLUETOOTH_SPEAKER_MAC}...")
                subprocess.Popen(["bluetoothctl", "connect", BLUETOOTH_SPEAKER_MAC], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

        # If adapter actually dropped, attempt recovery once
        print(f"⚠️ [BLUETOOTH] '{BLUETOOTH_HCI}' is DOWN, attempting recovery...")
        cls.ensure_adapter_up()
