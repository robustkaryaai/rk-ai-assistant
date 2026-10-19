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
    - One-time ambient noise calibration (not repeated every loop)
    - Automatically stops recording as soon as user finishes speaking
    - Fallback to native ALSA arecord if speech_recognition isn't installed
    - Hardware mute check
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.record_path = data_dir / "last_command.wav"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.is_hardware_muted = False

        # Cached VAD energy threshold — calibrated once at startup, not every loop.
        # This prevents the threshold from sky-rocketing when music is playing.
        self._energy_threshold: float = 350.0
        self._threshold_calibrated: bool = False

    def calibrate_once(self):
        """
        Calibrate ambient noise energy threshold once (call at startup, with speaker silent).
        Saves the result so record_command() doesn't re-calibrate every loop.
        """
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            r.energy_threshold = 350
            r.dynamic_energy_threshold = True
            with sr.Microphone() as source:
                print("🎙️ [VAD] Calibrating mic threshold (1s)...")
                r.adjust_for_ambient_noise(source, duration=1.0)
            self._energy_threshold = max(r.energy_threshold, 300)
            self._threshold_calibrated = True
            print(f"🎙️ [VAD] Threshold set to {self._energy_threshold:.0f}")
        except Exception as e:
            print(f"[VAD] Calibration failed, using default 350: {e}")
            self._energy_threshold = 350.0

    def record_command(self, duration: int = 7, silence_duration: float = 1.2) -> Optional[Path]:
        """
        Smart VAD Recording:
        - Uses pre-calibrated energy threshold so music doesn't throw it off.
        - Listens with automatic silence cutoff (fast response).
        - Falls back to arecord if speech_recognition isn't available.
        """
        if self.is_hardware_muted:
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

            # Use pre-calibrated threshold — never re-calibrate mid-session
            r.energy_threshold = self._energy_threshold
            r.dynamic_energy_threshold = False   # Don't let music raise the bar
            r.pause_threshold = silence_duration
            r.phrase_threshold = 0.2             # Start capturing speech quickly
            r.non_speaking_duration = silence_duration

            with sr.Microphone() as source:
                try:
                    # listen() blocks until phrase_time_limit or pause_threshold
                    audio = r.listen(
                        source,
                        timeout=None,           # No timeout — wait forever for speech
                        phrase_time_limit=duration
                    )
                    with open(self.record_path, "wb") as f:
                        f.write(audio.get_wav_data())

                    if self.record_path.exists() and self.record_path.stat().st_size > 1500:
                        return self.record_path

                except Exception as listen_err:
                    # WaitTimeoutError or other — just return None silently
                    pass

        except Exception as import_err:
            pass  # speech_recognition not installed, fall through to arecord

        # 2. Native ALSA arecord fallback (only if sr not available)
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
            subprocess.run(cmd, check=True, timeout=duration + 3)
            if self.record_path.exists() and self.record_path.stat().st_size > 1500:
                return self.record_path
        except Exception as e:
            print(f"[record] arecord error: {e}")

        return None

    def transcribe(self, client=None) -> str:
        """
        Transcribes the recorded command:
        1. Fast cloud Whisper STT via backend (/audio/:slug).
        2. Fallback to Google STT (speech_recognition) if cloud fails.
        """
        if not self.record_path.exists():
            return ""

        # Cloud transcription via RK_AI_HOME (Whisper on backend)
        if client:
            try:
                audio_bytes = self.record_path.read_bytes()
                res = client.send_audio(audio_bytes)
                text = res.get("text", "").strip()
                if text:
                    print(f"☁️ [STT] Cloud: '{text}'")
                    return text
            except Exception as e:
                print(f"[stt] Cloud STT error: {e}")

        # Local Google STT fallback (free, no API key, works offline via internet)
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            with sr.AudioFile(str(self.record_path)) as source:
                audio = r.record(source)
                try:
                    text = r.recognize_google(audio, language="en-IN").strip()
                    if text:
                        print(f"🔤 [STT] Local: '{text}'")
                        return text
                except sr.UnknownValueError:
                    pass  # Could not understand audio
                except sr.RequestError as e:
                    print(f"[stt] Google STT request failed: {e}")
        except Exception:
            pass

        return ""
