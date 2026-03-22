"""
Compatibility wrapper around the lightweight hybrid TTS module.
"""

from __future__ import annotations

import threading

from .config import FORCE_OFFLINE
from .hybrid_tts import contains_hindi, speak_with_options


_tts_lock = threading.Lock()


def speak(
    text: str,
    online: bool = True,
    allow_network_tts: bool = True,
    engine: str = "auto",
    gender: str = "female",
):
    """
    Preserve the assistant's existing speak() signature while routing to the
    new Flite-first hybrid TTS implementation.
    """
    spoken_text = str(text or "").strip()
    if not spoken_text:
        return

    allow_gtts = bool(online and allow_network_tts and not FORCE_OFFLINE)
    requested_engine = str(engine or "auto").strip().lower()

    # Offline-only call sites should never trigger network gTTS.
    if not allow_gtts:
        if requested_engine == "gtts":
            requested_engine = "espeak"
        elif requested_engine == "auto" and contains_hindi(spoken_text):
            requested_engine = "espeak"

    with _tts_lock:
        print(f"🔊 {spoken_text}", flush=True)
        speak_with_options(
            text=spoken_text,
            engine=requested_engine,
            gender=gender,
            allow_gtts=allow_gtts,
        )
