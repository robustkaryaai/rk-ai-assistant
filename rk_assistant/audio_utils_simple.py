"""
Compatibility wrapper around the lightweight hybrid TTS module.
"""

from __future__ import annotations

import threading

from .config import FORCE_OFFLINE
from .hybrid_tts import contains_hindi, speak_with_options
from .settings_sync import get_tts_config


_tts_lock = threading.Lock()


def speak(
    text: str,
    online: bool = True,
    allow_network_tts: bool = True,
    engine: str | None = None,
    gender: str | None = None,
    voice: str | None = None,
    language: str | None = None,
):
    """
    Preserve the assistant's existing speak() signature while routing to the
    new Flite-first hybrid TTS implementation.
    """
    spoken_text = str(text or "").strip()
    if not spoken_text:
        return

    profile = get_tts_config()
    requested_engine = str(engine or profile.get("engine") or "gtts").strip().lower()
    requested_gender = str(gender or profile.get("gender") or "female").strip().lower()
    requested_voice = voice or profile.get("voice")
    requested_language = str(language or profile.get("language") or "en").strip().lower()

    if requested_engine == "gtts":
        requested_language = "hi"
    elif requested_engine == "flite":
        requested_language = "en"

    allow_network_gtts = bool(online and allow_network_tts and not FORCE_OFFLINE)
    allow_gtts = allow_network_gtts

    # When gTTS is selected but the device is offline, fall back to local engines.
    if not allow_network_gtts:
        if requested_engine == "gtts":
            requested_engine = "espeak" if contains_hindi(spoken_text) else "flite"
        elif requested_engine == "auto" and contains_hindi(spoken_text):
            requested_engine = "espeak"

    with _tts_lock:
        print(f"🔊 {spoken_text}", flush=True)
        speak_with_options(
            text=spoken_text,
            engine=requested_engine,
            gender=requested_gender,
            voice=requested_voice,
            language=requested_language,
            allow_gtts=allow_gtts,
            allow_network_gtts=allow_network_gtts,
        )
