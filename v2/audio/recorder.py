import os
import queue
import subprocess
import threading
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
    Exact v1 SmartSTTEngine Background Streaming Implementation for v2:
    - Runs continuous listen_in_background() so the mic stream is ALWAYS open and warm.
    - Zero phrase truncation or single-word cutoff.
    - Captures full natural multi-word phrases and puts transcribed text in a thread-safe queue.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.record_path = data_dir / "last_command.wav"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.is_hardware_muted = False

        setup_microphone_volume()

        self._recognizer: Optional[sr.Recognizer] = None
        self._mic: Optional[sr.Microphone] = None
        self._stop_listening = None
        self.command_queue: queue.Queue[str] = queue.Queue()
        self._last_text = ""

        if SPEECH_RECOGNITION_AVAILABLE:
            try:
                self._recognizer = sr.Recognizer()
                cfg_file = self.data_dir / "mic_config.json"
                base_energy = 50
                if cfg_file.exists():
                    try:
                        import json
                        cfg = json.loads(cfg_file.read_text())
                        base_energy = int(cfg.get("energy_threshold", 50))
                    except Exception:
                        pass

                # Exact v1 SmartSTT Engine Parameters
                self._recognizer.energy_threshold = base_energy
                self._recognizer.dynamic_energy_threshold = True
                self._recognizer.dynamic_energy_ratio = 1.3
                self._recognizer.pause_threshold = 1.2
                self._recognizer.non_speaking_duration = 0.6
                self._recognizer.phrase_threshold = 0.2
                self._mic = sr.Microphone(sample_rate=16000)
            except Exception as e:
                print(f"[recorder] Error initializing SpeechRecognition: {e}", flush=True)

    def calibrate_once(self):
        """Calibrate ambient noise and start v1 background streaming listener."""
        setup_microphone_volume()
        if self._recognizer and self._mic:
            try:
                with no_alsa_err():
                    with self._mic as source:
                        self._recognizer.adjust_for_ambient_noise(source, duration=0.6)
                cfg_file = self.data_dir / "mic_config.json"
                floor_val = 50
                if cfg_file.exists():
                    try:
                        import json
                        cfg = json.loads(cfg_file.read_text())
                        floor_val = int(cfg.get("energy_threshold", 50))
                    except Exception:
                        pass
                self._recognizer.energy_threshold = max(self._recognizer.energy_threshold, floor_val)
                print(f"🎙️ [STT] v1 SmartSTT Background Listener Active (Energy: {self._recognizer.energy_threshold:.0f})", flush=True)
            except Exception as e:
                print(f"[recorder] Calibration notice: {e}", flush=True)

        self._start_background_listener()

    def _start_background_listener(self):
        if not SPEECH_RECOGNITION_AVAILABLE or self._recognizer is None or self._mic is None:
            return
        if self._stop_listening is not None:
            try:
                self._stop_listening(wait_for_stop=False)
            except Exception:
                pass
            self._stop_listening = None

        try:
            with no_alsa_err():
                self._stop_listening = self._recognizer.listen_in_background(
                    self._mic,
                    self._on_phrase_captured,
                    phrase_time_limit=15
                )
        except Exception as e:
            print(f"[recorder] Error starting background listener: {e}", flush=True)

    def _on_phrase_captured(self, recognizer, audio):
        """Callback invoked by speech_recognition background thread whenever a phrase completes."""
        if self.is_hardware_muted:
            return

        # 1. Exact v1 normalization boost
        boosted = _normalize_audio(audio)

        # Save to disk for sound_monitor background events
        try:
            with open(self.record_path, "wb") as f:
                f.write(boosted.get_wav_data())
        except Exception:
            pass

        # 2. Transcribe via Google STT (language='en-IN' with fallback to en-US)
        text = ""
        for lang in ["en-IN", "en-US"]:
            try:
                text = recognizer.recognize_google(boosted, language=lang).strip()
                if text:
                    break
            except sr.UnknownValueError:
                continue
            except Exception:
                pass

        if text:
            print(f"🔤 [STT] Heard: '{text}'", flush=True)
            self.command_queue.put(text)

    def record_command(self, duration: int = 10, silence_duration: float = 1.2) -> Optional[Path]:
        """
        Polls the background phrase queue.
        Returns Path to WAV if a phrase was transcribed, None if still waiting.
        """
        if self.is_hardware_muted:
            return None

        # Re-ensure background listener is running
        if self._stop_listening is None:
            self._start_background_listener()

        try:
            # Non-blocking check with small sleep
            text = self.command_queue.get(timeout=0.4)
            self._last_text = text
            if self.record_path.exists():
                return self.record_path
        except queue.Empty:
            pass

        return None

    def transcribe(self, client=None) -> str:
        """Returns the transcribed text from the background listener."""
        text = self._last_text
        self._last_text = ""
        return text
