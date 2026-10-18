import os
import hashlib
import subprocess
import shutil
from pathlib import Path
from typing import Optional

class TTSManager:
    """
    High-Quality Voice Engine (gTTS + Flite).
    Zero pyttsx3, Zero robotic raw eSpeak.
    - Priority 1: gTTS (Google natural neural speech, cached to MP3)
    - Priority 2: Flite (Fast, natural C-based speech engine, voice 'slt' / 'rms')
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_speech_file(self, text: str) -> Optional[str]:
        if not text:
            return None

        clean_text = text.strip()
        text_hash = hashlib.md5(clean_text.lower().encode("utf-8")).hexdigest()
        cache_file = self.cache_dir / f"{text_hash}.mp3"

        # 1. Instant Cache Hit
        if cache_file.exists() and cache_file.stat().st_size > 500:
            return str(cache_file)

        # 2. Try online gTTS (natural Google Voice)
        try:
            from gtts import gTTS
            tts = gTTS(text=clean_text, lang="en", tld="co.in", slow=False)
            tts.save(str(cache_file))
            if cache_file.exists() and cache_file.stat().st_size > 500:
                return str(cache_file)
        except Exception:
            pass

        # 3. Flite Offline Fallback (Natural, high quality human sound)
        wav_file = self.cache_dir / f"{text_hash}.wav"
        if shutil.which("flite"):
            try:
                # Using 'slt' (natural female voice) or 'rms'
                subprocess.run(
                    ["flite", "-voice", "slt", "-t", clean_text, "-o", str(wav_file)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
                if wav_file.exists() and wav_file.stat().st_size > 500:
                    return str(wav_file)
            except Exception:
                pass

        return None
