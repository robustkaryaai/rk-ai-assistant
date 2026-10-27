import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from ctypes import CFUNCTYPE, c_char_p, c_int, cdll
from contextlib import contextmanager

try:
    import audioop
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop
    except ImportError:
        audioop = None

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    sr = None
    SPEECH_RECOGNITION_AVAILABLE = False

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
    """Force hardware capture gain and PulseAudio source to 200% for enclosed box."""
    cfg_file = Path(__file__).resolve().parent.parent / "data" / "mic_config.json"
    source_vol = 200
    if cfg_file.exists():
        try:
            import json
            cfg = json.loads(cfg_file.read_text())
            source_vol = int(cfg.get("source_volume_percent", 200))
        except Exception:
            pass

    controls = ["Capture", "Mic", "Internal Mic", "Digital", "Input", "Boost", "Mic Boost"]
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


def _normalize_audio(audio_data, target_level=25000):
    """
    Exact v1 audio normalization:
    Scales peak audio up to 25000 (with up to 15x boost) so Google STT gets clear signal.
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None or audioop is None:
        return audio_data
    try:
        raw_data = audio_data.get_raw_data()
        max_val = audioop.max(raw_data, 2)
        if max_val == 0:
            return audio_data
        factor = target_level / max_val
        factor = min(factor, 15.0)  # Up to 15x boost for quiet mics
        if factor > 1.05:
            boosted_raw = audioop.mul(raw_data, 2, factor)
            return sr.AudioData(boosted_raw, audio_data.sample_rate, audio_data.sample_width)
    except Exception as e:
        print(f"[recorder] Normalization error: {e}", flush=True)
    return audio_data


class AudioRecorder:
    """
    Exact tune_mic + v1 Speech Recognition Engine:
    - Same recognizer settings as tune_mic option [t]
    - Direct Google STT with language='en-IN'
    - Dynamic energy adjustment (dynamic_energy_ratio=1.3, phrase_threshold=0.15)
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.record_path = data_dir / "last_command.wav"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.is_hardware_muted = False

        setup_microphone_volume()

        self._recognizer: Optional[sr.Recognizer] = None
        self._mic: Optional[sr.Microphone] = None
        self._last_audio_obj: Optional[sr.AudioData] = None

        if SPEECH_RECOGNITION_AVAILABLE:
            try:
                self._recognizer = sr.Recognizer()
                cfg_file = self.data_dir / "mic_config.json"
                base_energy = 35
                if cfg_file.exists():
                    try:
                        import json
                        cfg = json.loads(cfg_file.read_text())
                        base_energy = int(cfg.get("energy_threshold", 35))
                    except Exception:
                        pass

                # Exact tune_mic parameters
                self._recognizer.energy_threshold = base_energy
                self._recognizer.dynamic_energy_threshold = True
                self._recognizer.dynamic_energy_ratio = 1.3
                self._recognizer.phrase_threshold = 0.15
                self._recognizer.pause_threshold = 0.8
                self._recognizer.non_speaking_duration = 0.4
                self._mic = sr.Microphone(sample_rate=16000)
            except Exception as e:
                print(f"[recorder] Error initializing SpeechRecognition: {e}", flush=True)

    def calibrate_once(self):
        """tune_mic calibration."""
        setup_microphone_volume()
        if self._recognizer and self._mic:
            try:
                with no_alsa_err():
                    with self._mic as source:
                        self._recognizer.adjust_for_ambient_noise(source, duration=0.8)
                cfg_file = self.data_dir / "mic_config.json"
                floor_val = 35
                if cfg_file.exists():
                    try:
                        import json
                        cfg = json.loads(cfg_file.read_text())
                        floor_val = int(cfg.get("energy_threshold", 35))
                    except Exception:
                        pass
                self._recognizer.energy_threshold = max(self._recognizer.energy_threshold, floor_val)
                print(f"🎙️ [STT] Calibrated Energy Threshold: {self._recognizer.energy_threshold:.0f} (dynamic=True)", flush=True)
            except Exception as e:
                print(f"[recorder] Calibration notice: {e}", flush=True)

    def record_command(self, duration: int = 10, silence_duration: float = 0.8) -> Optional[Path]:
        """Record user speech exactly like tune_mic option [t]."""
        if self.is_hardware_muted:
            return None

        if self.record_path.exists():
            try:
                self.record_path.unlink()
            except Exception:
                pass

        if self._recognizer and self._mic:
            try:
                self._recognizer.pause_threshold = 0.8
                with no_alsa_err():
                    with self._mic as source:
                        audio = self._recognizer.listen(source, timeout=3, phrase_time_limit=max(duration, 10))

                # Normalize audio
                audio = _normalize_audio(audio)
                self._last_audio_obj = audio

                with open(self.record_path, "wb") as f:
                    f.write(audio.get_wav_data())

                if self.record_path.exists() and self.record_path.stat().st_size > 1000:
                    return self.record_path

            except sr.WaitTimeoutError:
                return None
            except Exception as e:
                pass

        return None

    def transcribe(self, client=None) -> str:
        """
        Exact tune_mic transcription:
        recognize_google(audio, language="en-IN")
        """
        audio_to_transcribe = None

        if self._last_audio_obj:
            audio_to_transcribe = self._last_audio_obj
        elif self.record_path.exists():
            if SPEECH_RECOGNITION_AVAILABLE:
                try:
                    r = sr.Recognizer()
                    with sr.AudioFile(str(self.record_path)) as source:
                        audio_to_transcribe = r.record(source)
                except Exception:
                    pass

        if not audio_to_transcribe and not self.record_path.exists():
            return ""

        # Primary: Exact tune_mic recognize_google with language="en-IN"
        if SPEECH_RECOGNITION_AVAILABLE and audio_to_transcribe:
            r = self._recognizer or sr.Recognizer()
            try:
                text = r.recognize_google(audio_to_transcribe, language="en-IN").strip()
                if text:
                    print(f"🔤 [STT] Heard: '{text}'", flush=True)
                    return text
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                print(f"[STT] Google API error: {e}", flush=True)
            except Exception as e:
                pass

            # Fallback to default en-US
            try:
                text = r.recognize_google(audio_to_transcribe).strip()
                if text:
                    print(f"🔤 [STT] Heard (en-US): '{text}'", flush=True)
                    return text
            except Exception:
                pass

        # Secondary fallback: Backend Cloud Whisper
        if client and self.record_path.exists():
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
