import os
import subprocess
import time
from pathlib import Path
from typing import Optional

class AudioRecorder:
    """
    Lightweight Audio Capture & STT for Pi Zero W (512MB RAM).
    Uses native ALSA 'arecord' for zero Python RAM overhead while listening.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.record_path = data_dir / "last_command.wav"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def record_command(self, duration: int = 5) -> Optional[Path]:
        """
        Record audio from default mic using ALSA arecord.
        Duration: 5 seconds (standard command window).
        """
        cmd = [
            "arecord",
            "-D", "default",
            "-f", "S16_LE",
            "-r", "16000",
            "-c", "1",
            "-d", str(duration),
            "-q",
            str(self.record_path)
        ]

        try:
            print(f"🎙️ [RECORD] Listening for {duration}s...")
            subprocess.run(cmd, check=True)
            if self.record_path.exists() and self.record_path.stat().st_size > 1000:
                return self.record_path
        except Exception as e:
            print(f"[record] arecord error: {e}")

        return None

    def transcribe(self, client=None) -> str:
        """
        Transcribes the recorded command.
        1. Fast cloud Whisper STT via backend (/audio/:slug).
        2. Fallback to local PocketSphinx / Google STT if available.
        """
        if not self.record_path.exists():
            return ""

        # Cloud transcription via RK_AI_HOME
        if client:
            try:
                audio_bytes = self.record_path.read_bytes()
                res = client.send_audio(audio_bytes)
                text = res.get("text", "").strip()
                if text:
                    return text
            except Exception as e:
                print(f"[stt] Cloud STT error: {e}")

        # Local speech_recognition fallback if installed
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            with sr.AudioFile(str(self.record_path)) as source:
                audio = r.record(source)
                try:
                    return r.recognize_google(audio).strip()
                except Exception:
                    pass
        except Exception:
            pass

        return ""
