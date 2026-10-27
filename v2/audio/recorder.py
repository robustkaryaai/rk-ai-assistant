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

# WebRTC VAD — lightweight C-extension, very low CPU on Pi Zero
try:
    import webrtcvad
    WEBRTCVAD_AVAILABLE = True
except ImportError:
    webrtcvad = None
    WEBRTCVAD_AVAILABLE = False

# numpy for RMS calculation — usually pre-installed on Pi OS
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
        # Boost PulseAudio capture source
        subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", f"{source_vol}%"], capture_output=True)
        subprocess.run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "0"], capture_output=True)
    except Exception:
        pass


# ─── Closed-Box Adaptive Equalizer & Peak AGC Normalizer ──────────────────────
# Closed acoustic boxes produce severe low-frequency resonance/boom (100-250Hz)
# while heavily attenuating mid and high clarity frequencies (1.5kHz - 4kHz).
# Here we apply:
#   1. A high-pass filter (approx 180Hz DC/box rumble cut) via simple IIR / difference
#   2. Adaptive Peak / RMS dynamic automatic gain control (AGC)
#   3. Strict peak limiting to avoid clipping.
# ─────────────────────────────────────────────────────────────────────────────

NOISE_FLOOR_RMS  = 40    # Ultra-sensitive for deeply muffled voice in box
TARGET_RMS       = 8000  # High target loudness for Google STT clarity
MAX_BOOST        = 25.0  # Up to 25x software gain for far-field / enclosed box
PEAK_CLIP_LIMIT  = 31500 # Hard ceiling to avoid int16 distortion


def _apply_acoustic_box_filter(samples: "np.ndarray") -> "np.ndarray":
    """
    High-pass filter (~180Hz cut) to remove box acoustic resonance / internal rumble.
    y[n] = x[n] - x[n-1] + 0.93 * y[n-1]
    Fast vector calculation in numpy.
    """
    if len(samples) < 2:
        return samples
    # Simple, high-efficiency first-order IIR DC / rumble block
    filtered = np.empty_like(samples)
    filtered[0] = samples[0]
    alpha = 0.93  # Cuts below ~180Hz at 16kHz sample rate
    # Run in chunks or iterative vector if small
    for i in range(1, len(samples)):
        filtered[i] = samples[i] - samples[i-1] + alpha * filtered[i-1]
    return filtered


def _smart_boost(audio_data):
    """
    Closed-box acoustic filtering + AGC dynamic boost.
    Falls back gracefully when numpy or sr are unavailable.
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return audio_data

    try:
        raw = audio_data.get_raw_data()
        n_samples = len(raw) // 2

        if n_samples == 0:
            return audio_data

        if NUMPY_AVAILABLE:
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)

            # 1. Filter out box cavity resonance / low-end rumble
            samples = _apply_acoustic_box_filter(samples)

            rms = float(np.sqrt(np.mean(samples ** 2)))

            # If under floor, mute frame so STT doesn't transcribe noise
            if rms < NOISE_FLOOR_RMS:
                return sr.AudioData(b'\x00' * len(raw), audio_data.sample_rate, audio_data.sample_width)

            # 2. Dynamic Automatic Gain Control (scale to TARGET_RMS, up to MAX_BOOST)
            boost = min(TARGET_RMS / max(rms, 1.0), MAX_BOOST)
            boosted = np.clip(samples * boost, -PEAK_CLIP_LIMIT, PEAK_CLIP_LIMIT)
            boosted_raw = boosted.astype(np.int16).tobytes()
        else:
            # Fallback without numpy
            total = sum(struct.unpack_from('<h', raw, i * 2)[0] ** 2 for i in range(n_samples))
            rms = (total / n_samples) ** 0.5
            if rms < NOISE_FLOOR_RMS:
                return sr.AudioData(b'\x00' * len(raw), audio_data.sample_rate, audio_data.sample_width)
            import audioop
            boost = min(int(TARGET_RMS / max(rms, 1.0)), int(MAX_BOOST))
            boosted_raw = audioop.mul(raw, 2, max(1, boost))

        return sr.AudioData(boosted_raw, audio_data.sample_rate, audio_data.sample_width)

    except Exception:
        return audio_data


# ─── WebRTC VAD Audio Filter ──────────────────────────────────────────────────
# WebRTC VAD operates on fixed-size PCM frames: 10ms, 20ms, or 30ms at 16kHz.
# We scan the full recording frame-by-frame and keep only the frames that VAD
# classifies as speech.  This strips silence/noise between and around words
# before the bytes are sent to Google STT, giving it a much cleaner signal.
#
# Aggressiveness 2 = balanced (0=least, 3=most aggressive noise rejection).
# On Pi Zero this runs in ~0.1ms per frame — effectively free.
# ─────────────────────────────────────────────────────────────────────────────

VAD_AGGRESSIVENESS   = 1    # 0–3; 1 = more forgiving for muffled box/far-field voice
VAD_FRAME_MS         = 30   # ms per frame — 30ms chunks at 16kHz = 480 samples
VAD_SAMPLE_RATE      = 16000
VAD_FRAME_BYTES      = VAD_FRAME_MS * VAD_SAMPLE_RATE * 2 // 1000  # = 960 bytes
# Minimum ratio of speech frames to keep — if fewer than this, treat as noise
VAD_MIN_SPEECH_RATIO = 0.05  # Keep even shorter utterances (lowered from 0.10)


def _vad_filter(audio_data):
    """
    Strip non-speech frames from an AudioData block using WebRTC VAD.

    Returns a new AudioData containing only the speech frames, or the original
    if VAD is not available or there isn't enough speech detected.
    """
    if not WEBRTCVAD_AVAILABLE or not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return audio_data  # Graceful no-op

    try:
        raw = audio_data.get_raw_data()
        vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

        speech_frames = []
        total_frames  = 0

        offset = 0
        while offset + VAD_FRAME_BYTES <= len(raw):
            frame = raw[offset: offset + VAD_FRAME_BYTES]
            try:
                is_speech = vad.is_speech(frame, VAD_SAMPLE_RATE)
            except Exception:
                is_speech = True  # If VAD errors on a frame, keep it
            if is_speech:
                speech_frames.append(frame)
            total_frames += 1
            offset += VAD_FRAME_BYTES

        if total_frames == 0:
            return audio_data

        speech_ratio = len(speech_frames) / total_frames
        if speech_ratio < VAD_MIN_SPEECH_RATIO:
            # Basically all noise — return the original so STT can still try
            return audio_data

        filtered_raw = b''.join(speech_frames)
        return sr.AudioData(filtered_raw, audio_data.sample_rate, audio_data.sample_width)

    except Exception:
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
                cfg_file = self.data_dir / "mic_config.json"
                base_energy = 50
                if cfg_file.exists():
                    try:
                        import json
                        cfg = json.loads(cfg_file.read_text())
                        base_energy = int(cfg.get("energy_threshold", 50))
                    except Exception:
                        pass

                # 🚀 Instant Speech Trigger & Low Latency:
                self._recognizer.energy_threshold = base_energy
                self._recognizer.dynamic_energy_threshold = False  # Fixed threshold so it doesn't float upward and miss words!
                self._recognizer.pause_threshold = 0.5            # Cut from 1.8s to 0.5s: Interprets the MOMENT you finish speaking!
                self._recognizer.phrase_threshold = 0.05          # Instant start on first syllable
                self._recognizer.non_speaking_duration = 0.3      # Only 300ms trailing silence required
                self._mic = sr.Microphone(sample_rate=16000)
            except Exception as e:
                print(f"[recorder] Error initializing SpeechRecognition: {e}", flush=True)

    def calibrate_once(self):
        """Calibrate ambient noise with configured hardware gain set."""
        setup_microphone_volume()
        if self._recognizer and self._mic:
            try:
                cfg_file = self.data_dir / "mic_config.json"
                base_energy = 50
                if cfg_file.exists():
                    try:
                        import json
                        cfg = json.loads(cfg_file.read_text())
                        base_energy = int(cfg.get("energy_threshold", 50))
                    except Exception:
                        pass

                print("🎙️ [STT] Calibrating microphone for room noise (1s)...", flush=True)
                with self._mic as source:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.8)
                # Keep floor at base energy (e.g. 50-80) for muffled box mic
                self._recognizer.energy_threshold = max(self._recognizer.energy_threshold, base_energy)
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
                # Ultra-responsive: stops and sends audio 0.5s after you finish talking!
                self._recognizer.pause_threshold = 0.5
                self._recognizer.non_speaking_duration = 0.3
                with no_alsa_err():
                    with self._mic as source:
                        # timeout=3 so idle checks loop smoothly without freezing
                        audio = self._recognizer.listen(source, timeout=3, phrase_time_limit=max(duration, 12))

                # 1. Strip non-speech frames (WebRTC VAD)
                audio = _vad_filter(audio)
                # 2. Noise gate + soft RMS boost
                audio = _smart_boost(audio)

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

        # 1. Primary: Direct Google STT with single high-accuracy request
        if SPEECH_RECOGNITION_AVAILABLE:
            try:
                r = sr.Recognizer()
                with sr.AudioFile(str(self.record_path)) as source:
                    audio = r.record(source)
                    # 1. VAD filter — strip silence/noise frames first
                    audio = _vad_filter(audio)
                    # 2. Noise gate + soft boost — clean amplification
                    audio = _smart_boost(audio)

                    # Direct single Google STT call (fastest response)
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
