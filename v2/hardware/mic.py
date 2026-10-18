import os
import subprocess
import shutil
from typing import Optional

class HardwareMicManager:
    """
    Hardware-level capture gain and mute control via ALSA amixer.
    Controls hardware mixers directly on Raspberry Pi (Capture, Mic, Internal Mic, Digital).
    """

    MIC_CONTROLS = ["Capture", "Mic", "Internal Mic", "Digital"]

    @classmethod
    def set_mute(cls, mute: bool) -> bool:
        """Hardware mute or unmute using amixer sset <control> mute/unmute or 0%/100%."""
        state_str = "mute" if mute else "unmute"
        pct_str = "0%" if mute else "100%"
        success = False

        if not shutil.which("amixer"):
            print(f"[hardware-mic] amixer not found. Cannot toggle hardware mic.")
            return False

        for ctrl in cls.MIC_CONTROLS:
            # 1. Try explicit mute toggle
            cmd1 = ["amixer", "sset", ctrl, state_str]
            res1 = subprocess.run(cmd1, capture_output=True, text=True)
            if res1.returncode == 0:
                success = True

            # 2. Also set gain level (0% if mute, 100% if unmute)
            cmd2 = ["amixer", "sset", ctrl, pct_str]
            res2 = subprocess.run(cmd2, capture_output=True, text=True)
            if res2.returncode == 0:
                success = True

        status_text = "MUTED (Hardware 0%)" if mute else "UNMUTED (Hardware 100%)"
        print(f"🎙️ [HARDWARE-MIC] Microphone {status_text}")
        return success

    @classmethod
    def mute(cls) -> bool:
        return cls.set_mute(True)

    @classmethod
    def unmute(cls) -> bool:
        return cls.set_mute(False)

    @classmethod
    def is_muted(cls) -> bool:
        if not shutil.which("amixer"):
            return False
        for ctrl in cls.MIC_CONTROLS:
            res = subprocess.run(["amixer", "sget", ctrl], capture_output=True, text=True)
            if res.returncode == 0:
                if "[off]" in res.stdout or "0%" in res.stdout:
                    return True
        return False
