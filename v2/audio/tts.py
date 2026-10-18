import os
import hashlib
import subprocess
from pathlib import Path
from typing import Optional

class TTSManager:
    """
    Lightweight Text-To-Speech with pre-caching.
    On Pi Zero W:
    - Checks local audio cache first (instant playback).
    - If missing, queries gTTS or fallback piper/espeak without blocking.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_speech_file(self, text: str) -> Optional[str]:
        if not text:
            return None

        # Hash text for cache key
        text_hash = hashlib.md5(text.strip().lower().encode("utf-8")).hexdigest()
        cache_file = self.cache_dir / f"{text_hash}.mp3"

        if cache_file.exists():
            return str(cache_file)

        # Generate on the fly via gTTS or eSpeak if offline
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang="en")
            tts.save(str(cache_file))
            return str(cache_file)
        except Exception:
            # Fast offline fallback: espeak to wav
            wav_file = self.cache_dir / f"{text_hash}.wav"
            try:
                subprocess.run(
                    ["espeak", "-w", str(wav_file), text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
                if wav_file.exists():
                    return str(wav_file)
            except Exception:
                pass

        return None
