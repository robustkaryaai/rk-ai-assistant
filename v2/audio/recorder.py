import os
import struct
import subprocess
import time
from pathlib import Path
from typing import Optional

from ctypes import CFUNCTYPE, c_char_p, c_int, cdll
from contextlib import contextmanager

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    sr = None
    SPEECH_RECOGNITION_AVAILABLE = False

try:
    import webrtcvad
    WEBRTCVAD_AVAILABLE = True
except ImportError:
    webrtcvad = None
    WEBRTCVAD_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    np = None
    NUMPY_AVAILABLE = False

# Silence ALSA C-library error dumps
try:
    ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
    def _py_error_handler(filename, line, function, err, fmt):
        pass
    _c_error_handler = ERROR_HANDLER_FUNC(_py_error_handler)
except Exception:
    _c_error_handler = None

@contextmanager
def no_alsa_err():
    if _c_error_handler:
        try:
            asound = cdll.LoadLibrary('libasound.so')
            asound.snd_lib_error_set_handler(_c_error_handler)
            yield
            asound.snd_lib_error_set_handler(None)
            return
        except Exception:
            pass
    yield


def setup_microphone_volume():
    """Force hardware and software capture gain to configured level (defaults to 200% for enclosed box)."""
    cfg_file = Path(__file__).resolve().parent.parent / "data" / "mic_config.json"
    source_vol = 200
    if cfg_file.exists():
        try:
            import json
            cfg = json.loads(cfg_file.read_text())
            source_vol = int(cfg.get("source_volume_percent", 200))
        except Exception:
            pass

    controls = [
        "Capture", "Mic", "Internal Mic", "Digital", "Input", "Boost",
        "Mic Boost", "Internal Mic Boost", "Capture Volume", "Mic Capture Volume"
    ]
    for control in controls:
        try:
            subprocess.run(["amixer", "sset", control, "100%"], capture_output=True)
            subprocess.run(["amixer", "sset", control, "cap"], capture_output=True)
            subprocess.run(["amixer", "sset", control, "unmute"], capture_output=True)
        except Exception:
            pass
    try:
        subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", f"{source_vol}%"], capture_output=True)
        subprocess.run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "0"], capture_output=True)
    except Exception:
        pass


NOISE_FLOOR_RMS  = 30
TARGET_RMS       = 8000
MAX_BOOST        = 25.0
PEAK_CLIP_LIMIT  = 31500


def _apply_acoustic_box_filter(samples: "np.ndarray") -> "np.ndarray":
    """High-pass filter (~180Hz) to remove box acoustic resonance / internal rumble."""
    if len(samples) < 2:
        return samples
    filtered = np.empty_like(samples)
    filtered[0] = samples[0]
    alpha = 0.93
    for i in range(1, len(samples)):
        filtered[i] = samples[i] - samples[i-1] + alpha * filtered[i-1]
    return filtered


def _smart_boost(audio_data):
    """Acoustic box filtering + automatic gain control."""
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return audio_data

    try:
        raw = audio_data.get_raw_data()
        n_samples = len(raw) // 2
        if n_samples == 0:
            return audio_data

        if NUMPY_AVAILABLE:
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            samples = _apply_acoustic_box_filter(samples)
            rms = float(np.sqrt(np.mean(samples ** 2)))
            if rms < NOISE_FLOOR_RMS:
                return audio_data

            boost = min(TARGET_RMS / max(rms, 1.0), MAX_BOOST)
            boosted = np.clip(samples * boost, -PEAK_CLIP_LIMIT, PEAK_CLIP_LIMIT)
            boosted_raw = boosted.astype(np.int16).tobytes()
        else:
            total = sum(struct.unpack_from('<h', raw, i * 2)[0] ** 2 for i in range(n_samples))
            rms = (total / n_samples) ** 0.5
            if rms < NOISE_FLOOR_RMS:
                return audio_data
            import audioop
            boost = min(int(TARGET_RMS / max(rms, 1.0)), int(MAX_BOOST))
            boosted_raw = audioop.mul(raw, 2, max(1, boost))

        return sr.AudioData(boosted_raw, audio_data.sample_rate, audio_data.sample_width)
    except Exception:
        return audio_data


class AudioRecorder:
    """
    Proven Robust Audio Capture & STT Engine:
    Uses PyAudio / SpeechRecognition with calibrated energy threshold,
    snappy pause_threshold (0.6s) for instant response like Alexa,
    and fallback to cloud whisper.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.record_path = data_dir / "last_command.wav"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.is_hardware_muted = False

        setup_microphone_volume()

        self._recognizer: Optional[sr.Recognizer] = None
        self._mic: Optional[sr.Microphone] = None
        if SPEECH_RECOGNITION_AVAILABLE:
            try:
                self._recognizer = sr.Recognizer()
                cfg_file = self.data_dir / "mic_config.json"
                base_energy = 60
                if cfg_file.exists():
                    try:
                        import json
                        cfg = json.loads(cfg_file.read_text())
                        base_energy = int(cfg.get("energy_threshold", 60))
                    except Exception:
                        pass

                # Fixed base energy so background noise never inflates threshold to 1000+
                self._recognizer.energy_threshold = base_energy
                self._recognizer.dynamic_energy_threshold = False
                # Alexa responsiveness: cuts off within 0.6s of finishing talking
                self._recognizer.pause_threshold = 0.6
                self._recognizer.phrase_threshold = 0.05
                self._recognizer.non_speaking_duration = 0.35
                self._mic = sr.Microphone(sample_rate=16000)
            except Exception as e:
                print(f"[recorder] Error initializing SpeechRecognition: {e}", flush=True)

    def calibrate_once(self):
        """Report locked threshold without running noisy calibration."""
        setup_microphone_volume()
        if self._recognizer and self._mic:
            cfg_file = self.data_dir / "mic_config.json"
            base_energy = 60
            if cfg_file.exists():
                try:
                    import json
                    cfg = json.loads(cfg_file.read_text())
                    base_energy = int(cfg.get("energy_threshold", 60))
                except Exception:
                    pass
            self._recognizer.energy_threshold = base_energy
            print(f"🎙️ [STT] Locked Sensitivity Threshold: {self._recognizer.energy_threshold:.0f} (Fast Cutoff: 0.6s)", flush=True)

    def record_command(self, duration: int = 10, silence_duration: float = 0.6) -> Optional[Path]:
        """
        Record user speech using PyAudio / SpeechRecognition.
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
                self._recognizer.pause_threshold = 0.6
                self._recognizer.non_speaking_duration = 0.35
                with no_alsa_err():
                    with self._mic as source:
                        audio = self._recognizer.listen(source, timeout=3, phrase_time_limit=max(duration, 12))

                # Normalize & boost audio for clarity
                audio = _smart_boost(audio)

                with open(self.record_path, "wb") as f:
                    f.write(audio.get_wav_data())

                if self.record_path.exists() and self.record_path.stat().st_size > 1500:
                    return self.record_path

            except sr.WaitTimeoutError:
                return None
            except Exception as e:
                pass

        return None

    def transcribe(self, client=None) -> str:
        """
        Transcribe captured audio:
        1. Google STT (en-IN with fallback to en-US)
        2. Backend Cloud STT fallback
        """
        if not self.record_path.exists():
            return ""

        # 1. Primary: SpeechRecognition Google engine
        if SPEECH_RECOGNITION_AVAILABLE:
            try:
                r = sr.Recognizer()
                with sr.AudioFile(str(self.record_path)) as source:
                    audio = r.record(source)
                    audio = _smart_boost(audio)
                    for lang in ["en-IN", "en-US"]:
                        try:
                            text = r.recognize_google(audio, language=lang).strip()
                            if text:
                                print(f"🔤 [STT] Recognized ({lang}): '{text}'", flush=True)
                                return text
                        except sr.UnknownValueError:
                            continue
            except sr.UnknownValueError:
                pass
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
