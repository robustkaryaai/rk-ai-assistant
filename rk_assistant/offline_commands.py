"""Offline command router."""

from __future__ import annotations

import datetime as dt
import time
from typing import Optional

from .audio_utils import play_audio_url, set_volume, speak, stop_process
from .config import OFFLINE_COMMANDS

OFFLINE_AI_RESPONSES = [f"Got it, noted {i}." for i in range(1, 101)]


def match_offline_command(text: str) -> Optional[str]:
    """Return matched command keyword if present."""
    text = (text or "").lower()
    for cmd in OFFLINE_COMMANDS:
        if cmd in text:
            return cmd
    return None


def handle_offline_command(cmd: str, music_proc) -> None:
    """Execute lightweight actions."""
    if cmd in {"play music", "resume music"}:
        # expecting streaming URL provided earlier? simple placeholder
        speak("No cached music URL. Please ask online.")
    elif cmd in {"pause music", "stop music"}:
        stop_process(music_proc)
        speak("Paused.")
    elif cmd == "volume up":
        set_volume(+5)
        speak("Volume up.")
    elif cmd == "volume down":
        set_volume(-5)
        speak("Volume down.")
    elif cmd in {"mute"}:
        set_volume(-50)
    elif cmd in {"unmute"}:
        set_volume(+20)
    elif cmd in {"time", "date"}:
        now = dt.datetime.now()
        speak(now.strftime("It is %H:%M on %A."))
    elif cmd in {"announcement", "announce"}:
        speak("Ready for your announcement.")
    else:
        speak(_offline_response(None))


def _offline_response(text: Optional[str]) -> str:
    idx = int(time.time()) % len(OFFLINE_AI_RESPONSES)
    return OFFLINE_AI_RESPONSES[idx]


def offline_ai_reply(text: str) -> str:
    return _offline_response(text)


