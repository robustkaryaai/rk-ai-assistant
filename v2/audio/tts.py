import os
import json
import hashlib
import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, Any

class TTSManager:
    """
    Multi-Engine High-Quality Voice Engine (gTTS, Flite, eSpeak).
    Synchronized with backend settings (ttsConfig):
    - engine: 'gtts' | 'flite' | 'espeak'
    - voice: voice id (e.g. 'slt', 'rms', 'co.in', 'en', 'hi')
    - language: language code (e.g. 'en', 'hi')
    """

    def __init__(self, cache_dir: Path, config_file: Optional[Path] = None):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = config_file or (cache_dir.parent / "tts_config.json")
        self.config: Dict[str, Any] = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        default = {
            "engine": "gtts",
            "voice": "co.in",
            "language": "en",
            "gender": "female"
        }
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text())
                if isinstance(data, dict):
                    default.update(data)
            except Exception:
                pass
        return default

    def set_config(self, new_config: Dict[str, Any]):
        if not isinstance(new_config, dict):
            return
        
        # Check if config actually changed to prevent duplicate file writes & log spam
        changed = False
        for k, v in new_config.items():
            if self.config.get(k) != v:
                changed = True
                break

        if not changed:
            return

        self.config.update(new_config)
        try:
            self.config_file.write_text(json.dumps(self.config, indent=2))
            print(f"🗣️ [TTS] Updated active engine to: {self.config.get('engine')} (voice={self.config.get('voice')})", flush=True)
        except Exception as e:
            print(f"⚠️ [TTS] Failed to persist tts_config: {e}", flush=True)

    def get_speech_file(self, text: str) -> Optional[str]:
        if not text:
            return None

        clean_text = text.strip()
        engine = str(self.config.get("engine", "gtts")).lower()
        voice = str(self.config.get("voice", "")).lower()
        language = str(self.config.get("language", "en")).lower()

        # Cache key based on text + engine + voice
        key = f"{clean_text}_{engine}_{voice}_{language}"
        text_hash = hashlib.md5(key.encode("utf-8")).hexdigest()

        # Try designated engine first
        if engine == "flite":
            file_path = self._generate_flite(clean_text, text_hash, voice)
            if file_path: return file_path
        elif engine == "espeak":
            file_path = self._generate_espeak(clean_text, text_hash, voice, language)
            if file_path: return file_path
        elif engine == "gtts":
            file_path = self._generate_gtts(clean_text, text_hash, voice, language)
            if file_path: return file_path

        # Fallbacks if chosen engine fails
        file_path = self._generate_gtts(clean_text, text_hash, "co.in", "en")
        if file_path: return file_path

        file_path = self._generate_flite(clean_text, text_hash, "slt")
        if file_path: return file_path

        file_path = self._generate_espeak(clean_text, text_hash, "en-us", "en")
        if file_path: return file_path

        return None

    def _generate_gtts(self, text: str, text_hash: str, voice: str, language: str) -> Optional[str]:
        cache_file = self.cache_dir / f"{text_hash}.mp3"
        if cache_file.exists() and cache_file.stat().st_size > 500:
            return str(cache_file)
        try:
            from gtts import gTTS
            tld = voice if voice in ("co.in", "com", "co.uk", "ca", "com.au") else "co.in"
            tts = gTTS(text=text, lang=language or "en", tld=tld, slow=False)
            tts.save(str(cache_file))
            if cache_file.exists() and cache_file.stat().st_size > 500:
                return str(cache_file)
        except Exception:
            pass
        return None

    def _generate_flite(self, text: str, text_hash: str, voice: str) -> Optional[str]:
        wav_file = self.cache_dir / f"{text_hash}.wav"
        if wav_file.exists() and wav_file.stat().st_size > 500:
            return str(wav_file)
        if shutil.which("flite"):
            try:
                flite_voice = voice if voice in ("slt", "rms", "awb", "kal") else "slt"
                subprocess.run(
                    ["flite", "-voice", flite_voice, "-t", text, "-o", str(wav_file)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
                if wav_file.exists() and wav_file.stat().st_size > 500:
                    return str(wav_file)
            except Exception:
                pass
        return None

    def _generate_espeak(self, text: str, text_hash: str, voice: str, language: str) -> Optional[str]:
        wav_file = self.cache_dir / f"{text_hash}.wav"
        if wav_file.exists() and wav_file.stat().st_size > 500:
            return str(wav_file)
        cmd = "espeak-ng" if shutil.which("espeak-ng") else ("espeak" if shutil.which("espeak") else None)
        if cmd:
            try:
                v_arg = voice if voice and len(voice) > 1 else (language or "en")
                subprocess.run(
                    [cmd, "-v", v_arg, "-s", "150", "-w", str(wav_file), text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
                if wav_file.exists() and wav_file.stat().st_size > 500:
                    return str(wav_file)
            except Exception:
                pass
        return None
