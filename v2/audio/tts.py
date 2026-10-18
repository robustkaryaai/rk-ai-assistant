import os
import hashlib
import subprocess
from pathlib import Path
from typing import Optional

class TTSManager:
    """
    gTTS-First Natural Voice Engine with Local Pre-Caching.
    - Generates crisp, natural, human-sounding speech via gTTS (lang='en', tld='co.in').
    - Caches all speech files locally in audio_cache so subsequent responses are INSTANT.
    - Eliminates robotic eSpeak output.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_speech_file(self, text: str) -> Optional[str]:
        if not text:
            return None

        # Clean text and hash for cache key
        clean_text = text.strip()
        text_hash = hashlib.md5(clean_text.lower().encode("utf-8")).hexdigest()
        cache_file = self.cache_dir / f"{text_hash}.mp3"

        # 1. Instant Cache Hit
        if cache_file.exists() and cache_file.stat().st_size > 500:
            return str(cache_file)

        # 2. Generate natural speech via gTTS (Google Text-to-Speech)
        try:
            from gtts import gTTS
            # Using tld='co.in' gives a crisp natural Indian English voice (perfect for 'Radhe Radhe')
            tts = gTTS(text=clean_text, lang="en", tld="co.in", slow=False)
            tts.save(str(cache_file))
            if cache_file.exists() and cache_file.stat().st_size > 500:
                return str(cache_file)
        except Exception as e:
            print(f"[tts] gTTS generation warning: {e}")

        # 3. Only if internet is completely down and gTTS fails: fallback wav
        wav_file = self.cache_dir / f"{text_hash}.wav"
        try:
            subprocess.run(
                ["espeak", "-w", str(wav_file), clean_text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            if wav_file.exists():
                return str(wav_file)
        except Exception:
            pass

        return None
