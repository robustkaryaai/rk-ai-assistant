import os
import subprocess
import time
from pathlib import Path
from typing import Optional

class AudioRecorder:
    """
    Smart Audio Capture & STT for Pi Zero W (512MB RAM).
    Features:
    - Smart VAD silence detection (via speech_recognition energy thresholding)
    - Automatically stops recording as soon as user finishes speaking
    - Fallback to native ALSA arecord if speech_recognition isn't installed
    - Hardware mute check
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.record_path = data_dir / "last_command.wav"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.is_hardware_muted = False

    def record_command(self, duration: int = 6, silence_duration: float = 1.0) -> Optional[Path]:
        """
        Smart VAD Recording:
        - If speech_recognition is available, listens with automatic silence cutoff (fast response).
        - If not, falls back to arecord.
        """
        if self.is_hardware_muted:
            print("🔇 [MIC] Microphone is currently muted.")
            return None

        # Delete previous recording
        if self.record_path.exists():
            try:
                self.record_path.unlink()
            except Exception:
                pass

        # 1. Smart VAD Recording using speech_recognition
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            r.pause_threshold = silence_duration
            r.energy_threshold = 250
            r.dynamic_energy_threshold = True

            with sr.Microphone() as source:
                r.adjust_for_ambient_noise(source, duration=0.2)
                print(f"🎙️ [SMART-VAD] Listening (auto-stops after {silence_duration}s silence)...")
                audio = r.listen(source, timeout=6, phrase_time_limit=duration)
                with open(self.record_path, "wb") as f:
                    f.write(audio.get_wav_data())

                if self.record_path.exists() and self.record_path.stat().st_size > 1000:
                    return self.record_path
        except Exception as vad_err:
            # Fallback to ALSA arecord
            pass

        # 2. Native ALSA arecord fallback
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
            print(f"🎙️ [RECORD] Listening via arecord ({duration}s)...")
            subprocess.run(cmd, check=True)
            if self.record_path.exists() and self.record_path.stat().st_size > 1000:
                return self.record_path
        except Exception as e:
            print(f"[record] arecord error: {e}")

        return None

    def transcribe(self, client=None) -> str:
        """
        Transcribes the recorded command:
        1. Fast cloud Whisper STT via backend (/audio/:slug).
        2. Fallback to Google STT if available.
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

        # Local speech_recognition fallback
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
