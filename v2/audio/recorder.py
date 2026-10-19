import os
import subprocess
import time
from pathlib import Path
from typing import Optional

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    sr = None
    SPEECH_RECOGNITION_AVAILABLE = False


def setup_microphone_volume():
    """Force hardware capture gain to 100% across all ALSA controls."""
    controls = ["Capture", "Mic", "Internal Mic", "Digital", "Input", "Boost"]
    for control in controls:
        try:
            subprocess.run(["amixer", "sset", control, "100%"], capture_output=True)
            subprocess.run(["amixer", "sset", control, "cap"], capture_output=True)
        except Exception:
            pass
    try:
        # Also maximize PulseAudio source volume
        subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", "100%"], capture_output=True)
    except Exception:
        pass


def _normalize_audio(audio_data, target_level=30000):
    """Normalize and boost soft microphone input up to 30000 peak (near 32767 max)."""
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return audio_data
    try:
        import audioop
        raw_data = audio_data.get_raw_data()
        max_val = audioop.max(raw_data, 2)
        if max_val == 0:
            return audio_data
        factor = target_level / max_val
        factor = min(factor, 20.0)  # Boost quiet microphones up to 20x
        if factor > 1.05:
            boosted_raw = audioop.mul(raw_data, 2, factor)
            return sr.AudioData(boosted_raw, audio_data.sample_rate, audio_data.sample_width)
    except Exception:
        pass
    return audio_data


class AudioRecorder:
    """
    Robust Audio Capture & STT for Pi Zero W.
    Combines v1's proven hardware gain + audio normalization + Google STT
    with v2's clean architecture and cloud fallback.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.record_path = data_dir / "last_command.wav"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.is_hardware_muted = False

        # Set hardware mic volume on startup
        setup_microphone_volume()

        self._recognizer: Optional[sr.Recognizer] = None
        self._mic: Optional[sr.Microphone] = None
        if SPEECH_RECOGNITION_AVAILABLE:
            try:
                self._recognizer = sr.Recognizer()
                self._recognizer.energy_threshold = 300
                self._recognizer.dynamic_energy_threshold = True
                self._recognizer.dynamic_energy_ratio = 1.5
                self._recognizer.pause_threshold = 1.0
                self._recognizer.phrase_threshold = 0.2
                self._recognizer.non_speaking_duration = 0.8
                self._mic = sr.Microphone(sample_rate=16000)
            except Exception as e:
                print(f"[recorder] Error initializing SpeechRecognition: {e}", flush=True)

    def calibrate_once(self):
        """Calibrate ambient noise with 100% hardware gain set."""
        setup_microphone_volume()
        if self._recognizer and self._mic:
            try:
                print("🎙️ [STT] Calibrating microphone for room noise (1s)...", flush=True)
                with self._mic as source:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.8)
                self._recognizer.energy_threshold = max(self._recognizer.energy_threshold, 100)
                print(f"🎙️ [STT] Baseline energy threshold: {self._recognizer.energy_threshold:.0f}", flush=True)
            except Exception as e:
                print(f"[STT] Calibration notice: {e}", flush=True)

    def record_command(self, duration: int = 10, silence_duration: float = 1.2) -> Optional[Path]:
        """
        Record user speech using speech_recognition (v1 method) with audio boost.
        Returns Path to WAV if speech captured, None if silence.
        """
        if self.is_hardware_muted:
            return None

        if self.record_path.exists():
            try:
                self.record_path.unlink()
            except Exception:
                pass

        if self._recognizer and self._mic:
            try:
                self._recognizer.pause_threshold = silence_duration
                with self._mic as source:
                    # timeout=5s so it gives you plenty of time to start speaking
                    audio = self._recognizer.listen(source, timeout=5, phrase_time_limit=duration)

                # Boost audio (v1 secret for high capture rate on Pi Zero)
                audio = _normalize_audio(audio)

                with open(self.record_path, "wb") as f:
                    f.write(audio.get_wav_data())

                if self.record_path.exists() and self.record_path.stat().st_size > 1500:
                    return self.record_path

            except sr.WaitTimeoutError:
                # Normal silence — return None so loop continues
                return None
            except Exception as e:
                # Other audio error — fall through to arecord
                pass

        # Native ALSA arecord fallback
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
            subprocess.run(cmd, check=True, timeout=duration + 3)
            if self.record_path.exists() and self.record_path.stat().st_size > 1500:
                return self.record_path
        except Exception:
            pass

        return None

    def transcribe(self, client=None) -> str:
        """
        Transcribe captured audio:
        1. Google STT with normalized audio (exact v1 engine that worked great).
        2. Backend Cloud STT fallback.
        """
        if not self.record_path.exists():
            return ""

        # 1. Primary: Direct Google STT with language hint (just like v1)
        if SPEECH_RECOGNITION_AVAILABLE:
            try:
                r = sr.Recognizer()
                with sr.AudioFile(str(self.record_path)) as source:
                    audio = r.record(source)
                    audio = _normalize_audio(audio)
                    text = r.recognize_google(audio, language="en-IN").strip()
                    if text:
                        print(f"🔤 [STT] Recognized: '{text}'", flush=True)
                        return text
            except sr.UnknownValueError:
                pass  # Audio was background noise / unintelligible
            except sr.RequestError as e:
                print(f"[STT] Google STT request error: {e}", flush=True)
            except Exception as e:
                print(f"[STT] Local STT error: {e}", flush=True)

        # 2. Secondary fallback: Backend Cloud Whisper
        if client:
            try:
                audio_bytes = self.record_path.read_bytes()
                res = client.send_audio(audio_bytes)
                text = res.get("text", "").strip()
                if text:
                    print(f"☁️ [STT] Cloud: '{text}'", flush=True)
                    return text
            except Exception as e:
                print(f"[STT] Cloud STT error: {e}", flush=True)

        return ""
