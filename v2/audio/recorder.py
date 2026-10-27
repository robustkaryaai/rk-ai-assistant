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
    """Force hardware capture gain to 100% using amixer."""
    controls = ["Capture", "Mic", "Internal Mic", "Digital", "Input", "Boost", "Mic Boost"]
    for control in controls:
        try:
            subprocess.run(["amixer", "sset", control, "100%"], capture_output=True)
            subprocess.run(["amixer", "sset", control, "cap"], capture_output=True)
            subprocess.run(["amixer", "sset", control, "unmute"], capture_output=True)
        except Exception:
            pass


def _normalize_audio(audio_data, target_level=25000):
    """
    Exact v1 audio normalization:
    Scales peak audio up to 25000 (with up to 15x boost) so Google STT gets clear, loud signal.
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
    Proven v1 SmartSTT Engine Port for v2:
    - Persistent open sr.Microphone() stream context
    - Natural pause_threshold (1.0s) & phrase_threshold (0.2s)
    - Dynamic energy adjustment (dynamic_energy_threshold = True, ratio 1.5)
    - Exact v1 _normalize_audio booster for crystal-clear Google STT
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
                # v1 Exact Battle-Tested Sensitivity
                self._recognizer.energy_threshold = 200
                self._recognizer.dynamic_energy_threshold = True
                self._recognizer.dynamic_energy_ratio = 1.5
                self._recognizer.pause_threshold = 1.0
                self._recognizer.phrase_threshold = 0.2
                self._recognizer.non_speaking_duration = 0.5
                self._mic = sr.Microphone(sample_rate=16000)
            except Exception as e:
                print(f"[recorder] Error initializing SpeechRecognition: {e}", flush=True)

    def calibrate_once(self):
        """Brief v1 0.5s ambient noise calibration with minimum floor of 100."""
        setup_microphone_volume()
        if self._recognizer and self._mic:
            try:
                with no_alsa_err():
                    with self._mic as source:
                        self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                # Keep floor sensible (100)
                self._recognizer.energy_threshold = max(self._recognizer.energy_threshold, 100)
                print(f"🎙️ [STT] v1 Calibrated Energy Threshold: {self._recognizer.energy_threshold:.0f} (dynamic=True)", flush=True)
            except Exception as e:
                print(f"[recorder] Calibration notice: {e}", flush=True)

    def record_command(self, duration: int = 10, silence_duration: float = 1.0) -> Optional[Path]:
        """
        Record user speech using v1 proven sr.Microphone + listen() loop.
        Saves WAV and holds audio object in memory for zero-distortion STT.
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
                self._recognizer.pause_threshold = 1.0
                with no_alsa_err():
                    with self._mic as source:
                        # timeout=3 for clean idle cycling
                        audio = self._recognizer.listen(source, timeout=3, phrase_time_limit=max(duration, 12))

                # Exact v1 normalization boost
                audio = _normalize_audio(audio)
                self._last_audio_obj = audio

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
        Exact v1 transcription:
        Direct Google Speech Recognition with v1 audio normalization.
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

        # 1. Primary: Direct Google STT
        if SPEECH_RECOGNITION_AVAILABLE and audio_to_transcribe:
            r = self._recognizer or sr.Recognizer()
            # Try with Google STT (first unnormalized, then normalized retry like v1)
            try:
                text = r.recognize_google(audio_to_transcribe)
                if text:
                    print(f"🔤 [STT] Heard: '{text}'", flush=True)
                    return text
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                print(f"[STT] Google API error: {e}", flush=True)
            except Exception as e:
                print(f"[STT] Recognition error: {e}", flush=True)

            # Retry with boosted normalization
            try:
                norm_audio = _normalize_audio(audio_to_transcribe)
                text = r.recognize_google(norm_audio)
                if text:
                    print(f"🔤 [STT] (Normalized) Heard: '{text}'", flush=True)
                    return text
            except Exception:
                pass

        # 2. Secondary fallback: Backend Cloud Whisper
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
